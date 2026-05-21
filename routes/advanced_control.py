
from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, render_template_string, request, redirect, url_for, flash, jsonify, current_app, send_file, session, Response, abort
from flask_login import login_required, current_user
from sqlalchemy import text, func, inspect, or_
from datetime import datetime, timedelta, timezone, date
from extensions import db, cache
from services.backup_service import AutomatedBackupManager
from models import User, SystemSettings, TenantRegistry
import utils
from utils import permission_required
from functools import wraps
import os
import string
import json
import shutil
from werkzeug.utils import secure_filename
from dataclasses import dataclass

advanced_bp = Blueprint('advanced', __name__, url_prefix='/advanced')


@dataclass(frozen=True)
class OwnerSectionMeta:
    key: str
    name: str
    endpoint: str
    icon: str
    order: int
    category: str


OWNER_SECTIONS = [
    OwnerSectionMeta('multi_tenant', 'Multi-Tenant', 'advanced.multi_tenant', 'building', 20, 'infrastructure'),
    OwnerSectionMeta('backup_manager', 'Backup Manager', 'advanced.backup_manager', 'save', 30, 'infrastructure'),
    OwnerSectionMeta('system_cloner', 'System Cloner', 'advanced.system_cloner', 'clone', 40, 'distribution'),
    OwnerSectionMeta('mobile_app_generator', 'Mobile Apps', 'advanced.mobile_app_generator', 'mobile-alt', 50, 'distribution'),
    OwnerSectionMeta('dashboard_links', 'Dashboard Links', 'advanced.dashboard_links', 'link', 60, 'governance'),
    OwnerSectionMeta('version_control', 'Version Control', 'advanced.version_control', 'code-branch', 70, 'governance'),
    OwnerSectionMeta('licensing', 'Licensing', 'advanced.licensing', 'key', 80, 'governance'),
    OwnerSectionMeta('module_manager', 'Module Manager', 'advanced.module_manager', 'puzzle-piece', 90, 'governance'),
    OwnerSectionMeta('feature_flags', 'Feature Flags', 'advanced.feature_flags', 'flag', 100, 'governance'),
    OwnerSectionMeta('system_health', 'System Health', 'advanced.system_health', 'heartbeat', 110, 'assurance'),
    OwnerSectionMeta('performance_profiler', 'Performance Profiler', 'advanced.performance_profiler', 'tachometer-alt', 115, 'assurance'),
    OwnerSectionMeta('database_optimizer', 'Database Optimizer', 'advanced.database_optimizer', 'database', 116, 'assurance'),
    OwnerSectionMeta('financial_control', 'Financial Control', 'advanced.financial_control', 'chart-line', 120, 'finance'),
    OwnerSectionMeta('accounting_control', 'Accounting Control', 'advanced.accounting_control', 'calculator', 130, 'finance'),
    OwnerSectionMeta('api_generator', 'API Generator', 'advanced.api_generator', 'code', 140, 'development'),
    OwnerSectionMeta('owner_checklist', 'قائمة الفحص', 'advanced.owner_smoke_checklist', 'clipboard-check', 150, 'assurance'),
]

SMOKE_TASKS = [
    {
        'key': 'backup_run',
        'title': 'إنشاء نسخة احتياطية',
        'description': 'تشغيل Backup Manager والتأكد من تسجيل النسخة.',
    },
    {
        'key': 'module_toggle',
        'title': 'تبديل وحدة',
        'description': 'تفعيل أو تعطيل وحدة مع التأكد من تسجيل العملية.',
    },
    {
        'key': 'security_update',
        'title': 'تحديث الأمان',
        'description': 'تعديل whitelist أو blacklist ومراجعة Owner Hub.',
    },
    {
        'key': 'health_run',
        'title': 'تشغيل فحص الصحة',
        'description': 'تشغيل Health Check وتوثيق النتيجة الأخيرة.',
    },
]

OWNER_GUIDE = [
    {
        'title': 'Backup Manager',
        'description': 'إدارة النسخ، الجدولة، والتحويلات بين قواعد البيانات.',
        'endpoint': 'advanced.backup_manager',
        'icon': 'save',
    },
    {
        'title': 'Multi-Tenant',
        'description': 'إضافة المستأجرين، مراقبة نشاطهم، وضبط الوحدات.',
        'endpoint': 'advanced.multi_tenant',
        'icon': 'building',
    },
    {
        'title': 'System Health',
        'description': 'تشغيل الفحوصات التلقائية ومراجعة النتائج التاريخية.',
        'endpoint': 'advanced.system_health',
        'icon': 'heartbeat',
    },
    {
        'title': 'Security Control',
        'description': 'التحكم بالدخول، قوائم IP، وحظر الدول.',
        'endpoint': 'security_control.security_control',
        'icon': 'shield-alt',
    },
    {
        'title': 'Version Control',
        'description': 'توثيق الإصدارات وتتبع الفروق المرتبطة بسجل المالك.',
        'endpoint': 'advanced.version_control',
        'icon': 'code-branch',
    },
]


SCHEDULE_LABELS = {
    'hourly': 'كل ساعة',
    'daily': 'يومي',
    'weekly': 'أسبوعي',
    'monthly': 'شهري',
}


def _sorted_owner_sections():
    return sorted(OWNER_SECTIONS, key=lambda meta: (meta.category, meta.order, meta.name))


@advanced_bp.context_processor
def inject_owner_sections_meta():
    sections = [
        {
            'key': meta.key,
            'name': meta.name,
            'endpoint': meta.endpoint,
            'icon': meta.icon,
            'order': meta.order,
            'category': meta.category,
        }
        for meta in _sorted_owner_sections()
    ]
    return {'owner_sections_meta': sections}


@advanced_bp.route('/owner-hub')
@login_required
@permission_required(SystemPermissions.ACCESS_OWNER_DASHBOARD)
def owner_hub():
    cache_key = "owner_hub_data"
    cached_data = cache.get(cache_key)
    
    if cached_data is None:
        tenant_list = _get_all_tenants()
        tenant_stats = {
            'total': len(tenant_list),
            'active': sum(1 for t in tenant_list if t['active']),
            'inactive': sum(1 for t in tenant_list if not t['active']),
        }
        backup_snapshot = _get_latest_backup_snapshot()
        auto_backup_enabled = SystemSettings.get_setting('auto_backup_enabled', False)
        auto_backup_schedule = SystemSettings.get_setting('auto_backup_schedule', '{}')
        schedule_info = {}
        if isinstance(auto_backup_schedule, str) and auto_backup_schedule:
            try:
                schedule_info = json.loads(auto_backup_schedule)
            except Exception:
                schedule_info = {}
        
        health_cache_key = "system_health_checks"
        health_cached = cache.get(health_cache_key)
        if health_cached is None:
            health_checks, overall_health = _collect_system_health_checks()
            cache.set(health_cache_key, (health_checks, overall_health), timeout=600)
        else:
            health_checks, overall_health = health_cached
        
        SystemSettings.set_setting('system_health_last_run',
                                   {'checks': health_checks, 'score': overall_health, 'time': datetime.now(timezone.utc).isoformat()},
                                   data_type='json')
        security_snapshot = _get_security_snapshot()
        security_summary = _summarize_security_snapshot(security_snapshot)
        license_info = _get_license_status()
        license_alert = None
        if license_info and license_info.get('status') in ('warning', 'expired'):
            license_alert = license_info
        last_denied_access = SystemSettings.get_setting('security_last_denied', None)
        backup_summary = _summarize_backup_snapshot(backup_snapshot, auto_backup_enabled)
        owner_alerts = _collect_owner_alerts(
            backup_summary=backup_summary,
            tenant_stats=tenant_stats,
            security_snapshot=security_snapshot,
            overall_health=overall_health,
            auto_backup_enabled=auto_backup_enabled,
            license_info=license_info,
        )
        db_stats = {
            'size': _get_db_size(),
            'records': _count_all_records(),
            'tenants': tenant_stats['total'],
        }
        
        cached_data = {
            'tenant_list': tenant_list,
            'tenant_stats': tenant_stats,
            'backup_snapshot': backup_snapshot,
            'auto_backup_enabled': auto_backup_enabled,
            'schedule_info': schedule_info,
            'health_checks': health_checks,
            'overall_health': overall_health,
            'security_snapshot': security_snapshot,
            'security_summary': security_summary,
            'license_info': license_info,
            'license_alert': license_alert,
            'last_denied_access': last_denied_access,
            'backup_summary': backup_summary,
            'owner_alerts': owner_alerts,
            'db_stats': db_stats,
        }
        cache.set(cache_key, cached_data, timeout=300)
    else:
        tenant_list = cached_data['tenant_list']
        tenant_stats = cached_data['tenant_stats']
        backup_snapshot = cached_data['backup_snapshot']
        auto_backup_enabled = cached_data['auto_backup_enabled']
        schedule_info = cached_data['schedule_info']
        health_checks = cached_data['health_checks']
        overall_health = cached_data['overall_health']
        security_snapshot = cached_data['security_snapshot']
        security_summary = cached_data['security_summary']
        license_info = cached_data['license_info']
        license_alert = cached_data['license_alert']
        last_denied_access = cached_data['last_denied_access']
        backup_summary = cached_data['backup_summary']
        owner_alerts = cached_data['owner_alerts']
        db_stats = cached_data['db_stats']
    quick_links = [
        {
            'label': 'إدارة النسخ',
            'icon': 'save',
            'endpoint': 'advanced.backup_manager',
            'status': 'success' if auto_backup_enabled else 'secondary',
        },
        {
            'label': 'Multi-Tenant',
            'icon': 'building',
            'endpoint': 'advanced.multi_tenant',
            'status': 'primary' if tenant_stats['active'] else 'secondary',
        },
        {
            'label': 'الصحة الشاملة',
            'icon': 'heartbeat',
            'endpoint': 'advanced.system_health',
            'status': 'success' if overall_health >= 80 else 'warning' if overall_health >= 60 else 'danger',
        },
        {
            'label': 'الأمان الشبكي',
            'icon': 'shield-alt',
            'endpoint': 'security_control.security_control',
            'status': 'success' if security_snapshot['status'] == 'ok' else 'warning',
        },
    ]
    owner_log = SystemSettings.get_setting('owner_action_log', [])
    if not isinstance(owner_log, list):
        owner_log = []
    checklist_state = _load_smoke_checklist_state()
    checklist_progress = {
        'completed': len(checklist_state['completed']),
        'total': len(SMOKE_TASKS),
        'last_run': checklist_state['timestamp'],
    }
    return render_template(
        'advanced/owner_hub.html',
        tenant_stats=tenant_stats,
        backup_snapshot=backup_snapshot,
        auto_backup_enabled=auto_backup_enabled,
        schedule_info=schedule_info,
        health_checks=health_checks,
        overall_health=overall_health,
        security_snapshot=security_snapshot,
        db_stats=db_stats,
        quick_links=quick_links,
        backup_summary=backup_summary,
        security_summary=security_summary,
        license_info=license_info,
        license_alert=license_alert,
        last_denied_access=last_denied_access,
        owner_alerts=owner_alerts,
        owner_log=owner_log[:8],
        owner_guide=OWNER_GUIDE,
        checklist_progress=checklist_progress,
    )


@advanced_bp.route('/owner-smoke-checklist', methods=['GET', 'POST'])
@permission_required(SystemPermissions.ACCESS_OWNER_DASHBOARD)
def owner_smoke_checklist():
    state = _load_smoke_checklist_state()
    if request.method == 'POST':
        completed = [task['key'] for task in SMOKE_TASKS if request.form.get(task['key']) == 'on']
        new_state = {
            'completed': completed,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        SystemSettings.set_setting('owner_smoke_checklist', new_state, data_type='json')
        _log_owner_action('owner.checklist_update', None, {'completed': len(completed)})
        flash('✅ تم تحديث قائمة الفحص', 'success')
        return redirect(url_for('advanced.owner_smoke_checklist'))
    progress = {
        'completed': len(state['completed']),
        'total': len(SMOKE_TASKS),
    }
    return render_template(
        'advanced/owner_checklist.html',
        tasks=SMOKE_TASKS,
        state=state,
        progress=progress,
        last_run=state['timestamp'],
    )

@advanced_bp.route('/db-merger', methods=['GET', 'POST'])
@permission_required(SystemPermissions.ACCESS_OWNER_DASHBOARD)
def db_merger():
    """معالج دمج قواعد البيانات"""
    
    # Calculate basic stats for the template
    stats = {
        'current_db_size': 'N/A',
        'total_tables': 0,
        'total_records': 0
    }
    
    try:
        from sqlalchemy import text, inspect
        # Size
        try:
            size_bytes = db.session.execute(text("SELECT pg_database_size(current_database())")).scalar()
            size_mb = round(size_bytes / (1024 * 1024), 2)
            stats['current_db_size'] = f"{size_mb} MB"
        except Exception:
            stats['current_db_size'] = "Unknown"

        # Tables
        try:
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            stats['total_tables'] = len(tables)
        except Exception:
            current_app.logger.warning('financial operation failed silently in advanced_control.py', exc_info=True)
        
    except Exception as e:
        current_app.logger.exception("Error in db_merger stats")

    preview = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'preview':
            # Dummy preview logic for now since real logic is complex
            preview = {
                'file_name': 'dummy.sql',
                'comparison': []
            }
            flash('This is a simulation. Merge logic needs implementation.', 'info')
        elif action == 'execute':
             flash('Merge executed (simulation).', 'success')
             return redirect(url_for('advanced.db_merger'))

    return render_template('advanced/db_merger.html', stats=stats, preview=preview)


@advanced_bp.route('/multi-tenant', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_TENANTS)
def multi_tenant():
    """إدارة Multi-Tenant المتقدمة - نسخ متعددة مع تحكم كامل"""
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create_tenant':
            tenant_name = request.form.get('tenant_name')
            tenant_db = request.form.get('tenant_db')
            tenant_domain = request.form.get('tenant_domain', '')
            tenant_logo = request.form.get('tenant_logo', '')
            tenant_company_name = request.form.get('tenant_company_name', '')
            tenant_system_name = request.form.get('tenant_system_name', '')
            tenant_favicon = request.form.get('tenant_favicon', '')
            tenant_max_users = request.form.get('tenant_max_users', '10')
            tenant_modules = request.form.getlist('tenant_modules')
            if not _validate_safe_slug(tenant_name):
                flash('❌ اسم الـ Tenant يجب أن يكون بدون مسافات أو محارف خاصة', 'danger')
                return redirect(url_for('advanced.multi_tenant'))

            existing_tenant = SystemSettings.query.filter_by(key=f'tenant_{tenant_name}_db').first()
            if existing_tenant:
                flash('❌ هذا الـ Tenant موجود مسبقاً', 'danger')
                return redirect(url_for('advanced.multi_tenant'))

            schema_name = _make_tenant_schema_name(tenant_name)
            if not schema_name:
                flash('❌ اسم الـ Tenant غير صالح لإنشاء schema', 'danger')
                return redirect(url_for('advanced.multi_tenant'))

            existing_registry = TenantRegistry.query.filter_by(slug=tenant_name).first()
            if existing_registry:
                flash('❌ هذا الـ Tenant مسجل مسبقاً في Registry', 'danger')
                return redirect(url_for('advanced.multi_tenant'))

            existing_schema = TenantRegistry.query.filter_by(schema_name=schema_name).first()
            if existing_schema:
                flash('❌ اسم الـ schema مستخدم مسبقاً', 'danger')
                return redirect(url_for('advanced.multi_tenant'))

            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_db', value=tenant_db))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_active', value='True'))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_domain', value=tenant_domain))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_logo', value=tenant_logo))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_company_name', value=tenant_company_name))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_system_name', value=tenant_system_name))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_favicon', value=tenant_favicon))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_max_users', value=tenant_max_users))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_modules', value=json.dumps(tenant_modules)))
            db.session.add(SystemSettings(key=f'tenant_{tenant_name}_created_at', value=datetime.now(timezone.utc).isoformat()))
            
            if not tenant_db or not str(tenant_db).strip().startswith('postgresql://'):
                flash('❌ قاعدة بيانات الـ Tenant يجب أن تكون PostgreSQL (postgresql://...)', 'danger')
                return redirect(url_for('advanced.multi_tenant'))

            domain_norm = (tenant_domain or '').strip().lower()
            if domain_norm:
                existing_domain = TenantRegistry.query.filter(func.lower(TenantRegistry.domain) == domain_norm).first()
                if existing_domain:
                    flash('❌ هذا الدومين مستخدم مسبقاً لTenant آخر. يجب أن يكون الدومين فريد لكل Tenant.', 'danger')
                    return redirect(url_for('advanced.multi_tenant'))
                existing = SystemSettings.query.filter(
                    SystemSettings.key.like('tenant_%_domain'),
                    func.lower(SystemSettings.value) == domain_norm
                ).first()
                if existing:
                    flash('❌ هذا الدومين مستخدم مسبقاً لTenant آخر. يجب أن يكون الدومين فريد لكل Tenant.', 'danger')
                    return redirect(url_for('advanced.multi_tenant'))

            display_name = (tenant_company_name or tenant_system_name or tenant_name or '').strip() or tenant_name
            db.session.add(TenantRegistry(
                slug=tenant_name,
                schema_name=schema_name,
                display_name=display_name,
                domain=domain_norm or None,
                is_active=True,
            ))
            
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                flash('حدث خطأ أثناء الحفظ', 'danger')
                return redirect(url_for('advanced.multi_tenant'))
            try:
                cache.delete("all_tenants_list")
                cache.delete("tenant_domains:v1")
                from models import SystemSettings as _SS
                _SS.set_setting('assets_version', int(datetime.now(timezone.utc).timestamp()), data_type='number')
            except Exception:
                current_app.logger.warning('cache invalidation failed silently in advanced_control.py', exc_info=True)
            _log_owner_action('multi_tenant.create', tenant_name, {
                'db': tenant_db,
                'modules': tenant_modules,
            })
            
            flash(f'✅ تم إنشاء Tenant: {tenant_name}', 'success')
            return redirect(url_for('advanced.multi_tenant'))
        
        elif action == 'toggle_tenant':
            tenant_name = request.form.get('tenant_name')
            if not _validate_safe_slug(tenant_name):
                flash('❌ اسم الـ Tenant غير صالح', 'danger')
                return redirect(url_for('advanced.multi_tenant'))
            setting = SystemSettings.query.filter_by(key=f'tenant_{tenant_name}_active').first()
            if setting:
                setting.value = 'False' if setting.value == 'True' else 'True'
                registry = TenantRegistry.query.filter_by(slug=tenant_name).first()
                if registry:
                    registry.is_active = setting.value == 'True'
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    current_app.logger.exception('commit error')
                    flash('حدث خطأ أثناء الحفظ', 'danger')
                    return redirect(url_for('advanced.multi_tenant'))
                _log_owner_action('multi_tenant.toggle', tenant_name, {
                    'new_status': setting.value,
                })
                flash(f'✅ تم تحديث حالة: {tenant_name}', 'success')
            return redirect(url_for('advanced.multi_tenant'))
        
        elif action == 'delete_tenant':
            tenant_name = request.form.get('tenant_name')
            confirm_token = request.form.get('confirm_token', '')
            if not _validate_safe_slug(tenant_name):
                flash('❌ اسم الـ Tenant غير صالح', 'danger')
                return redirect(url_for('advanced.multi_tenant'))
            if confirm_token != tenant_name:
                flash('❌ اكتب اسم الـ Tenant للتأكيد قبل الحذف', 'danger')
                return redirect(url_for('advanced.multi_tenant'))
                                         
            SystemSettings.query.filter(SystemSettings.key.like(f'tenant_{tenant_name}_%')).delete()
            TenantRegistry.query.filter_by(slug=tenant_name).delete()
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                flash('حدث خطأ أثناء الحفظ', 'danger')
                return redirect(url_for('advanced.multi_tenant'))
            try:
                cache.delete("all_tenants_list")
                cache.delete("tenant_domains:v1")
            except Exception:
                current_app.logger.warning('cache invalidation failed silently in advanced_control.py', exc_info=True)
            _log_owner_action('multi_tenant.delete', tenant_name)
            flash(f'✅ تم حذف Tenant: {tenant_name}', 'success')
            return redirect(url_for('advanced.multi_tenant'))
        
        elif action == 'update_tenant':
            tenant_name = request.form.get('tenant_name')
            if not _validate_safe_slug(tenant_name):
                flash('❌ اسم الـ Tenant غير صالح', 'danger')
                return redirect(url_for('advanced.multi_tenant'))
            tenant_domain = request.form.get('tenant_domain', '')
            tenant_logo = request.form.get('tenant_logo', '')
            tenant_company_name = request.form.get('tenant_company_name', '')
            tenant_system_name = request.form.get('tenant_system_name', '')
            tenant_favicon = request.form.get('tenant_favicon', '')
            tenant_max_users = request.form.get('tenant_max_users', '10')
            tenant_modules = request.form.getlist('tenant_modules')

            domain_norm = (tenant_domain or '').strip().lower()
            if domain_norm:
                existing = SystemSettings.query.filter(
                    SystemSettings.key.like('tenant_%_domain'),
                    func.lower(SystemSettings.value) == domain_norm
                ).first()
                if existing and not str(existing.key or '').startswith(f'tenant_{tenant_name}_'):
                    flash('❌ هذا الدومين مستخدم مسبقاً لTenant آخر. يجب أن يكون الدومين فريد لكل Tenant.', 'danger')
                    return redirect(url_for('advanced.multi_tenant'))
                existing_domain = TenantRegistry.query.filter(func.lower(TenantRegistry.domain) == domain_norm).first()
                if existing_domain and existing_domain.slug != tenant_name:
                    flash('❌ هذا الدومين مستخدم مسبقاً لTenant آخر. يجب أن يكون الدومين فريد لكل Tenant.', 'danger')
                    return redirect(url_for('advanced.multi_tenant'))
            
                             
            _update_tenant_setting(f'tenant_{tenant_name}_domain', tenant_domain)
            _update_tenant_setting(f'tenant_{tenant_name}_logo', tenant_logo)
            _update_tenant_setting(f'tenant_{tenant_name}_company_name', tenant_company_name)
            _update_tenant_setting(f'tenant_{tenant_name}_system_name', tenant_system_name)
            _update_tenant_setting(f'tenant_{tenant_name}_favicon', tenant_favicon)
            _update_tenant_setting(f'tenant_{tenant_name}_max_users', tenant_max_users)
            _update_tenant_setting(f'tenant_{tenant_name}_modules', json.dumps(tenant_modules))

            registry = TenantRegistry.query.filter_by(slug=tenant_name).first()
            if not registry:
                schema_name = _make_tenant_schema_name(tenant_name)
                if schema_name:
                    registry = TenantRegistry(slug=tenant_name, schema_name=schema_name, is_active=True)
                    db.session.add(registry)
            if registry:
                display_name = (tenant_company_name or tenant_system_name or tenant_name or '').strip() or tenant_name
                registry.display_name = display_name
                registry.domain = domain_norm or None
            
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                flash('حدث خطأ أثناء الحفظ', 'danger')
                return redirect(url_for('advanced.multi_tenant'))
            try:
                cache.delete("all_tenants_list")
                cache.delete("tenant_domains:v1")
                from models import SystemSettings as _SS
                _SS.set_setting('assets_version', int(datetime.now(timezone.utc).timestamp()), data_type='number')
            except Exception:
                current_app.logger.warning('cache invalidation failed silently in advanced_control.py', exc_info=True)
            _log_owner_action('multi_tenant.update', tenant_name, {
                'domain': tenant_domain,
                'max_users': tenant_max_users,
                'modules': tenant_modules,
            })
            flash(f'✅ تم تحديث Tenant: {tenant_name}', 'success')
            return redirect(url_for('advanced.multi_tenant'))
    
                      
    tenant_list = _get_all_tenants()
    
                     
    available_modules = _get_available_modules_list()
    
              
    page = request.args.get('page', 1, type=int)
    per_page = 10
    tenant_records = _prepare_tenants(_get_all_tenants())
    filters = _build_tenant_filters(request.args)
    tenant_list = _filter_tenants(tenant_records, filters)
    paginated_tenants = tenant_list[(page - 1) * per_page: page * per_page]
    total_pages = (len(tenant_list) + per_page - 1) // per_page
    
    available_modules = _get_available_modules_list()
    module_lookup = {module['key']: module for module in available_modules}
    
    stats = _build_tenant_stats(tenant_records)
    module_usage = _calculate_module_usage(tenant_records, available_modules)
    
    return render_template('advanced/multi_tenant.html', 
                         tenants=paginated_tenants,
                         available_modules=available_modules,
                         module_lookup=module_lookup,
                         module_usage=module_usage,
                         stats=stats,
                         filters=filters,
                         visible_count=len(tenant_list),
                         page=page,
                         total_pages=total_pages,
                         per_page=per_page)


@advanced_bp.route('/dashboard-links', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def dashboard_links():
    """إدارة روابط الداشبورد - إخفاء/إظهار"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'toggle_link':
            link_key = request.form.get('link_key')
            visible = request.form.get('visible') == 'on'
            
            setting = SystemSettings.query.filter_by(key=f'dashboard_link_{link_key}').first()
            if setting:
                setting.value = str(visible)
            else:
                db.session.add(SystemSettings(key=f'dashboard_link_{link_key}', value=str(visible)))
            
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                flash('حدث خطأ أثناء الحفظ', 'danger')
                return redirect(url_for('advanced.dashboard_links'))
            _log_owner_action('dashboard_links.toggle', link_key, {'visible': visible})
            flash(f'✅ تم تحديث: {link_key}', 'success')
            return redirect(url_for('advanced.dashboard_links'))
    
    available_links = [
        {'key': 'customers', 'name': 'العملاء', 'icon': 'users'},
        {'key': 'service', 'name': 'الصيانة', 'icon': 'wrench'},
        {'key': 'sales', 'name': 'المبيعات', 'icon': 'shopping-cart'},
        {'key': 'warehouses', 'name': 'المستودعات', 'icon': 'warehouse'},
        {'key': 'vendors', 'name': 'الموردين', 'icon': 'truck'},
        {'key': 'partners', 'name': 'الشركاء', 'icon': 'handshake'},
        {'key': 'shipments', 'name': 'الشحنات', 'icon': 'ship'},
        {'key': 'payments', 'name': 'الدفعات', 'icon': 'money-bill-wave'},
        {'key': 'checks', 'name': 'الشيكات', 'icon': 'money-check'},
        {'key': 'expenses', 'name': 'النفقات', 'icon': 'receipt'},
        {'key': 'ledger', 'name': 'دفتر الأستاذ', 'icon': 'book'},
        {'key': 'currencies', 'name': 'العملات', 'icon': 'dollar-sign'},
        {'key': 'reports', 'name': 'التقارير', 'icon': 'chart-bar'},
        {'key': 'shop', 'name': 'المتجر', 'icon': 'store'},
    ]
    
    for link in available_links:
        setting = SystemSettings.query.filter_by(key=f'dashboard_link_{link["key"]}').first()
        link['visible'] = setting.value == 'True' if setting else True
    
    return render_template('advanced/dashboard_links.html', links=available_links)


@advanced_bp.route('/version-control', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def version_control():
    """إدارة النسخ والإصدارات"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create_version':
            version_name = request.form.get('version_name')
            if not _validate_safe_slug(version_name):
                flash('❌ اسم الإصدار يجب أن يكون بدون مسافات أو رموز خاصة', 'danger')
                return redirect(url_for('advanced.version_control'))
            version_notes = request.form.get('version_notes')
            version_diff = request.form.get('version_diff')
            summary = {
                'notes': version_notes,
                'diff': version_diff,
            }
            
            db.session.add(SystemSettings(key=f'version_{version_name}_date', value=datetime.now(timezone.utc).isoformat()))
            db.session.add(SystemSettings(key=f'version_{version_name}_notes', value=version_notes))
            if version_diff:
                db.session.add(SystemSettings(key=f'version_{version_name}_diff', value=version_diff))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                flash('حدث خطأ أثناء الحفظ', 'danger')
                return redirect(url_for('advanced.version_control'))
            _log_owner_action('version.create', version_name, summary)
            
            flash(f'✅ تم إنشاء إصدار: {version_name}', 'success')
            return redirect(url_for('advanced.version_control'))
        
        elif action == 'delete_version':
            version_name = request.form.get('version_name')
            if not _validate_safe_slug(version_name):
                flash('❌ اسم الإصدار يجب أن يكون بدون مسافات أو رموز خاصة', 'danger')
                return redirect(url_for('advanced.version_control'))
            SystemSettings.query.filter(SystemSettings.key.like(f'version_{version_name}_%')).delete()
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                flash('حدث خطأ أثناء الحفظ', 'danger')
                return redirect(url_for('advanced.version_control'))
            _log_owner_action('version.delete', version_name)
            flash(f'✅ تم حذف الإصدار: {version_name}', 'success')
            return redirect(url_for('advanced.version_control'))
    
    versions = []
    version_settings = SystemSettings.query.filter(
        SystemSettings.key.like('version_%_date')
    ).all()
    
    for v in version_settings:
        name = v.key.replace('version_', '').replace('_date', '')
        notes_setting = SystemSettings.query.filter_by(key=f'version_{name}_notes').first()
        diff_setting = SystemSettings.query.filter_by(key=f'version_{name}_diff').first()
        versions.append({
            'name': name,
            'date': v.value,
            'notes': notes_setting.value if notes_setting else '',
            'diff': diff_setting.value if diff_setting else ''
        })
    
                                      
    versions.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('advanced/version_control.html', versions=versions)


@advanced_bp.route('/licensing', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def licensing():
    """إدارة التراخيص والتفعيل"""
    if request.method == 'POST':
        license_key = request.form.get('license_key')
        client_name = request.form.get('client_name')
        expiry_date = request.form.get('expiry_date')
        max_users = request.form.get('max_users')
        
        license_data = {
            'key': license_key,
            'client': client_name,
            'expiry': expiry_date,
            'max_users': max_users,
            'activated_at': datetime.now(timezone.utc).isoformat()
        }
        
        setting = SystemSettings.query.filter_by(key='license_info').first()
        if setting:
            setting.value = json.dumps(license_data)
        else:
            db.session.add(SystemSettings(key='license_info', value=json.dumps(license_data)))
        
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('commit error')
            return jsonify({'success': False, 'error': 'حدث خطأ داخلي'}), 500
        flash('✅ تم تفعيل الترخيص', 'success')
        return redirect(url_for('advanced.licensing'))
    
    license_setting = SystemSettings.query.filter_by(key='license_info').first()
    license_info = json.loads(license_setting.value) if license_setting and license_setting.value else {}
    if license_info.get('expiry'):
        try:
            expiry_dt = datetime.strptime(license_info['expiry'], '%Y-%m-%d').date()
            days_left = (expiry_dt - date.today()).days
            license_info['days_left'] = days_left
            if days_left <= 0:
                license_info['status'] = 'expired'
            elif days_left <= 30:
                license_info['status'] = 'warning'
            else:
                license_info['status'] = 'active'
        except Exception:
            license_info['status'] = 'unknown'
    else:
        license_info['status'] = 'missing'
        license_info['days_left'] = None
    
    return render_template('advanced/licensing.html', license=license_info)


MODULE_CATALOG = [
    {'key': 'customers', 'name': 'إدارة العملاء', 'icon': 'users', 'color': 'primary', 'dependencies': []},
    {'key': 'service', 'name': 'الصيانة', 'icon': 'wrench', 'color': 'success', 'dependencies': ['customers']},
    {'key': 'sales', 'name': 'المبيعات', 'icon': 'shopping-cart', 'color': 'info', 'dependencies': ['customers']},
    {'key': 'warehouses', 'name': 'المستودعات', 'icon': 'warehouse', 'color': 'warning', 'dependencies': []},
    {'key': 'vendors', 'name': 'الموردين', 'icon': 'truck', 'color': 'secondary', 'dependencies': []},
    {'key': 'partners', 'name': 'الشركاء', 'icon': 'handshake', 'color': 'success', 'dependencies': []},
    {'key': 'shipments', 'name': 'الشحنات', 'icon': 'ship', 'color': 'info', 'dependencies': ['warehouses', 'vendors']},
    {'key': 'payments', 'name': 'الدفعات', 'icon': 'money-bill-wave', 'color': 'success', 'dependencies': ['customers']},
    {'key': 'checks', 'name': 'الشيكات', 'icon': 'money-check', 'color': 'warning', 'dependencies': ['payments']},
    {'key': 'expenses', 'name': 'النفقات', 'icon': 'receipt', 'color': 'danger', 'dependencies': []},
    {'key': 'ledger', 'name': 'دفتر الأستاذ', 'icon': 'book', 'color': 'dark', 'dependencies': []},
    {'key': 'shop', 'name': 'المتجر الإلكتروني', 'icon': 'store', 'color': 'primary', 'dependencies': ['customers', 'sales', 'warehouses']},
    {'key': 'reports', 'name': 'التقارير', 'icon': 'chart-bar', 'color': 'info', 'dependencies': ['customers', 'sales', 'payments']},
]
MODULE_LOOKUP = {m['key']: m for m in MODULE_CATALOG}


@advanced_bp.route('/module-manager', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def module_manager():
    """مدير الوحدات - تفعيل/تعطيل"""
    module_states = _get_module_states()
    if request.method == 'POST':
        module_key = request.form.get('module_key')
        enabled = request.form.get('enabled') == 'on'
        deps = MODULE_LOOKUP.get(module_key, {}).get('dependencies', [])
        if enabled:
            unmet = [dep for dep in deps if not module_states.get(dep, True)]
            if unmet:
                names = ', '.join(MODULE_LOOKUP.get(dep, {}).get('name', dep) for dep in unmet)
                flash(f'❌ يجب تفعيل الوحدات: {names} قبل تفعيل {module_key}', 'danger')
                return redirect(url_for('advanced.module_manager'))
        
        # Use centralized setter for consistency and cache management
        SystemSettings.set_setting(
            key=f'module_{module_key}_enabled',
            value=enabled,
            data_type='boolean',
            description=f'Enable/Disable {module_key} module'
        )
        
        # Log the action
        _log_owner_action('module.toggle', module_key, {'enabled': enabled})
        
        flash(f'✅ تم تحديث: {module_key}', 'success')
        return redirect(url_for('advanced.module_manager'))
    
    modules = []
    module_states = _get_module_states()
    for entry in MODULE_CATALOG:
        setting = SystemSettings.query.filter_by(key=f'module_{entry["key"]}_enabled').first()
        enabled = module_states.get(entry['key'], True)
        dependencies = entry.get('dependencies', [])
        dependencies_detail = [
            {'key': dep, 'name': MODULE_LOOKUP.get(dep, {}).get('name', dep), 'enabled': module_states.get(dep, True)}
            for dep in dependencies
        ]
        modules.append({
            **entry,
            'enabled': enabled,
            'updated_at': setting.updated_at if setting else None,
            'dependencies_detail': dependencies_detail,
            'deps_ready': all(d['enabled'] for d in dependencies_detail),
        })
    stats = {
        'total': len(modules),
        'active': sum(1 for m in modules if m['enabled']),
        'blocked': sum(1 for m in modules if not m['deps_ready']),
    }
    
    return render_template('advanced/module_manager.html', modules=modules, stats=stats)


def _get_module_states():
    states = {}
    for entry in MODULE_CATALOG:
        setting = SystemSettings.query.filter_by(key=f'module_{entry["key"]}_enabled').first()
        states[entry['key']] = setting.value != 'False' if setting else True
    return states


@advanced_bp.route('/backup-manager', methods=['GET', 'POST'])
@permission_required(SystemPermissions.BACKUP_DATABASE)
def backup_manager():
    backup_dir = current_app.config.get("BACKUP_DB_DIR") or os.path.join(current_app.instance_path, "backups")
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create_backup':
            try:
                custom_name = (request.form.get('backup_name') or '').strip() or None
                if custom_name and not _validate_safe_slug(custom_name):
                    flash('❌ اسم النسخة يجب أن يكون بدون مسافات أو رموز خاصة', 'danger')
                    return redirect(url_for('advanced.backup_manager'))

                from extensions import perform_backup_db
                success, message, backup_path = perform_backup_db(current_app)
                if not success or not backup_path or not os.path.exists(backup_path):
                    flash(f'❌ {message}', 'danger')
                    return redirect(url_for('advanced.backup_manager'))

                final_path = backup_path
                if custom_name:
                    base = os.path.splitext(os.path.basename(backup_path))[0]
                    suffix = base.replace("backup_", "", 1)
                    desired = os.path.join(backup_dir, f'backup_{custom_name}_{suffix}.dump')
                    try:
                        os.replace(backup_path, desired)
                        info_src = os.path.splitext(backup_path)[0] + ".info"
                        info_dst = os.path.splitext(desired)[0] + ".info"
                        if os.path.exists(info_src):
                            os.replace(info_src, info_dst)
                        final_path = desired
                    except Exception:
                        final_path = backup_path

                size_mb = os.path.getsize(final_path) / (1024 * 1024)
                flash(f'✅ تم إنشاء نسخة احتياطية', 'success')
                _log_owner_action('backup.create', os.path.basename(final_path), {
                    'size_mb': round(size_mb, 2),
                    'path': final_path.replace(current_app.root_path, '')
                })
            except Exception as e:
                _record_backup_failure('فشل إنشاء النسخة الاحتياطية')
                current_app.logger.exception('internal error')
                flash('حدث خطأ داخلي', 'danger')
            
            return redirect(url_for('advanced.backup_manager'))
        
        elif action == 'schedule_backup':
            schedule_type = request.form.get('schedule_type')
            schedule_time = request.form.get('schedule_time', '03:00')
            if not _validate_time_string(schedule_time):
                flash('❌ صيغة الوقت غير صحيحة (HH:MM)', 'danger')
                return redirect(url_for('advanced.backup_manager'))
            if schedule_type not in SCHEDULE_LABELS:
                flash('❌ نوع الجدولة غير مدعوم', 'danger')
                return redirect(url_for('advanced.backup_manager'))
            
            setting = SystemSettings.query.filter_by(key='auto_backup_enabled').first()
            if setting:
                setting.value = 'True'
            else:
                db.session.add(SystemSettings(key='auto_backup_enabled', value='True'))
            
            schedule_setting = SystemSettings.query.filter_by(key='auto_backup_schedule').first()
            if schedule_setting:
                schedule_setting.value = json.dumps({'type': schedule_type, 'time': schedule_time})
            else:
                db.session.add(SystemSettings(key='auto_backup_schedule', value=json.dumps({'type': schedule_type, 'time': schedule_time})))
            
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                return jsonify({'success': False, 'error': 'حدث خطأ داخلي'}), 500
            flash(f'✅ تم جدولة النسخ الاحتياطي: {schedule_type}', 'success')
            _log_owner_action('backup.schedule', schedule_type, {
                'time': schedule_time,
            })
            return redirect(url_for('advanced.backup_manager'))
        
        elif action == 'convert_database':
            flash('❌ تحويل قاعدة البيانات غير مدعوم. النظام يعمل على PostgreSQL فقط.', 'danger')
            return redirect(url_for('advanced.backup_manager'))
    
    backups = []
    now = datetime.now()
    if os.path.exists(backup_dir):
        for filename in sorted(os.listdir(backup_dir), reverse=True):
            if filename.endswith(('.dump', '.sql')):
                filepath = os.path.join(backup_dir, filename)
                size = os.path.getsize(filepath) / (1024 * 1024)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                age_hours = (now - mtime).total_seconds() / 3600
                backups.append({
                    'name': filename,
                    'size': f'{size:.2f} MB',
                    'date': mtime.strftime('%Y-%m-%d %H:%M'),
                    'timestamp': mtime.isoformat(),
                    'age_hours': round(age_hours, 2),
                    'type': 'db_dump'
                })
    
    # Scan JSON exports
    json_backups = []
    exports_dir = os.path.join(current_app.root_path, 'exports')
    if os.path.exists(exports_dir):
        for filename in sorted(os.listdir(exports_dir), reverse=True):
            if filename.endswith('.json'):
                filepath = os.path.join(exports_dir, filename)
                size = os.path.getsize(filepath) / (1024 * 1024)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                age_hours = (now - mtime).total_seconds() / 3600
                json_backups.append({
                    'name': filename,
                    'size': f'{size:.2f} MB',
                    'date': mtime.strftime('%Y-%m-%d %H:%M'),
                    'timestamp': mtime.isoformat(),
                    'age_hours': round(age_hours, 2),
                    'type': 'json'
                })

    auto_backup_enabled = SystemSettings.query.filter_by(key='auto_backup_enabled').first()
    auto_backup_schedule = SystemSettings.query.filter_by(key='auto_backup_schedule').first()
    
    schedule_info = {}
    if auto_backup_schedule and auto_backup_schedule.value:
        try:
            schedule_info = json.loads(auto_backup_schedule.value)
        except Exception:
            schedule_info = {}
    
    current_db_type = _detect_current_db_type()
    auto_enabled = auto_backup_enabled.value == 'True' if auto_backup_enabled else False
    schedule_status = _describe_schedule_status(auto_enabled, schedule_info)
    backup_summary = _build_backup_summary(backups + json_backups)
    
    backup_failures = SystemSettings.get_setting('backup_failures', [])
    if not isinstance(backup_failures, list):
        backup_failures = []
    
    return render_template('advanced/backup_manager.html', 
                         backups=backups,
                         json_backups=json_backups,
                         auto_backup_enabled=auto_enabled,
                         schedule_info=schedule_info,
                         current_db_type=current_db_type,
                         schedule_status=schedule_status,
                         backup_summary=backup_summary,
                         recent_backups=backups[:3],
                         backup_failures=backup_failures)


@advanced_bp.route('/download-backup/<filename>')
@permission_required(SystemPermissions.BACKUP_DATABASE)
def download_backup(filename):
    """تحميل نسخة احتياطية"""
    try:
        if filename.endswith('.json'):
            exports_dir = os.path.join(current_app.root_path, 'exports')
            filepath = os.path.join(exports_dir, secure_filename(filename))
        else:
            backup_dir = current_app.config.get("BACKUP_DB_DIR") or os.path.join(current_app.instance_path, "backups")
            filepath = os.path.join(backup_dir, secure_filename(filename))
        
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True, download_name=filename)
        else:
            flash('❌ الملف غير موجود', 'danger')
            return redirect(url_for('advanced.backup_manager'))
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('advanced.backup_manager'))


@advanced_bp.route('/restore-json-backup/<filename>', methods=['POST'])
@permission_required(SystemPermissions.BACKUP_DATABASE)
def restore_json_backup(filename):
    """استعادة نسخة احتياطية من ملف JSON"""
    try:
        exports_dir = os.path.join(current_app.root_path, 'exports')
        filepath = os.path.join(exports_dir, secure_filename(filename))
        confirm_token = request.form.get('confirm_token')
        
        if confirm_token != filename:
            flash('❌ يجب كتابة اسم النسخة للتأكيد قبل الاستعادة', 'danger')
            return redirect(url_for('advanced.backup_manager'))
        
        if not os.path.exists(filepath):
            flash('❌ الملف غير موجود', 'danger')
            return redirect(url_for('advanced.backup_manager'))
        
        from extensions import perform_backup_db
        # Always take a safety backup first
        safety_ok, _, safety_path = perform_backup_db(current_app)
        if not safety_ok:
             flash('⚠️ فشل إنشاء نسخة أمان تلقائية، لكن سيتم متابعة الاستعادة بحذر.', 'warning')
        else:
             flash(f'💾 تم حفظ نسخة أمان: {os.path.basename(safety_path)}', 'info')

        from import_data_json import import_from_json
        success, messages = import_from_json(filepath, app=current_app)
        
        if success:
            flash(f'✅ تم استعادة البيانات من {filename} بنجاح.', 'success')
            _log_owner_action('backup.restore_json', filename, {'status': 'success'})
        else:
            flash(f'❌ حدثت أخطاء أثناء الاستعادة. راجع السجلات.', 'danger')
            for msg in messages:
                if "Error" in msg or "Warning" in msg:
                    flash(msg, 'warning')
            _log_owner_action('backup.restore_json', filename, {'status': 'failed', 'errors': messages[:5]})
            
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        
    return redirect(url_for('advanced.backup_manager'))



@advanced_bp.route('/restore-backup/<filename>', methods=['POST'])
@permission_required(SystemPermissions.BACKUP_DATABASE)
def restore_backup(filename):
    """استعادة نسخة احتياطية"""
    try:
        backup_dir = current_app.config.get("BACKUP_DB_DIR") or os.path.join(current_app.instance_path, "backups")
        backup_path = os.path.join(backup_dir, secure_filename(filename))
        confirm_token = request.form.get('confirm_token')
        
        if confirm_token != filename:
            flash('❌ يجب كتابة اسم النسخة للتأكيد قبل الاستعادة', 'danger')
            return redirect(url_for('advanced.backup_manager'))
        
        if not os.path.exists(backup_path) or not filename.endswith('.dump'):
            flash('❌ الملف غير موجود', 'danger')
            return redirect(url_for('advanced.backup_manager'))
        
        from extensions import perform_backup_db, restore_database
        safety_ok, _, safety_path = perform_backup_db(current_app)
        if not safety_ok or not safety_path:
            flash('❌ فشل حفظ نسخة الأمان قبل الاستعادة', 'danger')
            return redirect(url_for('advanced.backup_manager'))

        ok, msg = restore_database(current_app, backup_path)
        if ok:
            flash(f'✅ تم استعادة النسخة: {filename}', 'success')
            flash(f'💾 تم حفظ نسخة أمان: {os.path.basename(safety_path)}', 'info')
            _log_owner_action('backup.restore', filename, {
                'safety_backup': os.path.basename(safety_path),
            })
        else:
            flash(f'❌ {msg}', 'danger')
    
    except Exception as e:
        _record_backup_failure(f'فشل استعادة النسخة ({filename})')
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
    
    return redirect(url_for('advanced.backup_manager'))


@advanced_bp.route('/delete-backup/<filename>', methods=['POST'])
@permission_required(SystemPermissions.BACKUP_DATABASE)
def delete_backup(filename):
    """حذف نسخة احتياطية"""
    try:
        backup_dir = current_app.config.get("BACKUP_DB_DIR") or os.path.join(current_app.instance_path, "backups", "db")
        filepath = os.path.join(backup_dir, secure_filename(filename))
        confirm_token = request.form.get('confirm_token')
        
        if confirm_token != filename:
            flash('❌ يجب كتابة اسم النسخة للتأكيد قبل الحذف', 'danger')
            return redirect(url_for('advanced.backup_manager'))
        
        if os.path.exists(filepath) and filename.endswith('.dump'):
            os.remove(filepath)
            info_file = os.path.splitext(filepath)[0] + ".info"
            if os.path.exists(info_file):
                try:
                    os.remove(info_file)
                except Exception:
                    current_app.logger.debug('file operation failed in advanced_control.py', exc_info=True)
            flash(f'✅ تم حذف النسخة: {filename}', 'success')
            _log_owner_action('backup.delete', filename)
        else:
            flash('❌ الملف غير موجود', 'danger')
    except Exception as e:
        _record_backup_failure(f'فشل حذف النسخة ({filename})')
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
    
    return redirect(url_for('advanced.backup_manager'))


@advanced_bp.route('/toggle-auto-backup', methods=['POST'])
@permission_required(SystemPermissions.BACKUP_DATABASE)
def toggle_auto_backup():
    """تفعيل/تعطيل النسخ التلقائي"""
    try:
        setting = SystemSettings.query.filter_by(key='auto_backup_enabled').first()
        if setting:
            setting.value = 'False' if setting.value == 'True' else 'True'
        else:
            db.session.add(SystemSettings(key='auto_backup_enabled', value='True'))
        
        db.session.commit()
        
        status = setting.value if setting else 'True'
        if status == 'True':
            flash('✅ تم تفعيل النسخ الاحتياطي التلقائي', 'success')
            _log_owner_action('backup.auto_toggle', 'enabled')
        else:
            flash('⚠️ تم تعطيل النسخ الاحتياطي التلقائي', 'warning')
            _log_owner_action('backup.auto_toggle', 'disabled')
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
    
    return redirect(url_for('advanced.backup_manager'))


@advanced_bp.route('/test-db-connection', methods=['POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def test_db_connection():
    """اختبار الاتصال بقاعدة البيانات"""
    try:
        from sqlalchemy import create_engine
        
        connection_string = request.form.get('connection_string')
        
        if not connection_string:
            return jsonify({'success': False, 'message': 'Connection string مطلوب'})
        
                        
        test_engine = create_engine(connection_string, echo=False)
        
        with test_engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            
            if result == 1:
                                    
                try:
                    version = conn.execute(text("SELECT version()")).scalar()
                except Exception:
                    version = "غير متاح"
                
                return jsonify({
                    'success': True,
                    'message': 'الاتصال ناجح!',
                    'version': version
                })
            else:
                return jsonify({'success': False, 'message': 'فشل الاتصال'})
                
    except Exception as e:
        current_app.logger.exception('internal error')
        return jsonify({'success': False, 'message': 'حدث خطأ داخلي'})


@advanced_bp.route('/api-generator', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def api_generator():
    """مولد API تلقائي"""
    if request.method == 'POST':
        table_name = request.form.get('table_name')
        endpoints = request.form.getlist('endpoints')
        
        _log_owner_action('api_generator.create', table_name, {'endpoints': endpoints})
        flash(f'✅ تم إنشاء API لـ {table_name}', 'success')
        return redirect(url_for('advanced.api_generator'))
    
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    
    return render_template('advanced/api_generator.html', tables=tables)


@advanced_bp.route('/feature-flags', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def feature_flags():
    """إدارة Feature Flags"""
    if request.method == 'POST':
        flag_key = request.form.get('flag_key')
        enabled = request.form.get('enabled') == 'on'
        
        setting = SystemSettings.query.filter_by(key=f'feature_{flag_key}').first()
        if setting:
            setting.value = str(enabled)
        else:
            db.session.add(SystemSettings(key=f'feature_{flag_key}', value=str(enabled)))
        
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('commit error')
            flash('حدث خطأ أثناء الحفظ', 'danger')
            return redirect(url_for('advanced.feature_flags'))
        _log_owner_action('feature_flags.toggle', flag_key, {'enabled': enabled})
        flash(f'✅ تم تحديث: {flag_key}', 'success')
        return redirect(url_for('advanced.feature_flags'))
    
    flags = [
                                                                                                                               
        {'key': 'auto_backup', 'name': 'نسخ احتياطي تلقائي', 'description': 'نسخ يومية تلقائية'},
        {'key': 'email_notifications', 'name': 'إشعارات البريد', 'description': 'إرسال تنبيهات بالبريد'},
        {'key': 'whatsapp_notifications', 'name': 'إشعارات واتساب', 'description': 'إرسال رسائل واتساب'},
        {'key': 'dark_mode', 'name': 'الوضع الداكن', 'description': 'تفعيل الثيم الداكن'},
        {'key': 'advanced_search', 'name': 'البحث المتقدم', 'description': 'بحث ذكي بالذكاء الاصطناعي'},
        {'key': 'auto_gl_sync', 'name': 'مزامنة GL تلقائية', 'description': 'مزامنة دفتر الأستاذ تلقائياً'},
        {'key': 'barcode_scanner', 'name': 'قارئ الباركود', 'description': 'تفعيل مسح الباركود'},
        {'key': 'online_shop', 'name': 'المتجر الإلكتروني', 'description': 'تفعيل المتجر'},
        {'key': 'multi_currency', 'name': 'عملات متعددة', 'description': 'دعم عملات متعددة'},
    ]
    
    for flag in flags:
        setting = SystemSettings.query.filter_by(key=f'feature_{flag["key"]}').first()
        flag['enabled'] = setting.value == 'True' if setting else False
    
    return render_template('advanced/feature_flags.html', flags=flags)


@advanced_bp.route('/system-health', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_HEALTH)
def system_health():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'fix_permissions':
            try:
                dirs_to_fix = ['instance', 'instance/backups', 'AI', 'static/uploads']                             
                for dir_path in dirs_to_fix:
                    full_path = os.path.join(current_app.root_path, dir_path)
                    os.makedirs(full_path, exist_ok=True)
                flash('✅ تم إصلاح الصلاحيات', 'success')
            except Exception as e:
                current_app.logger.exception('internal error')
                flash('حدث خطأ داخلي', 'danger')
        
        elif action == 'clear_cache':
            try:
                cache_dirs = ['__pycache__', 'instance/__pycache__']
                for cache_dir in cache_dirs:
                    cache_path = os.path.join(current_app.root_path, cache_dir)
                    if os.path.exists(cache_path):
                        shutil.rmtree(cache_path)
                flash('✅ تم تنظيف الكاش', 'success')
            except Exception as e:
                current_app.logger.exception('internal error')
                flash('حدث خطأ داخلي', 'danger')
        
        elif action == 'optimize_db':
            try:
                from extensions import perform_vacuum_optimize
                perform_vacuum_optimize(current_app)
                flash('✅ تم تحسين قاعدة البيانات', 'success')
            except Exception as e:
                current_app.logger.exception('internal error')
                flash('حدث خطأ داخلي', 'danger')
        elif action == 'auto_run':
            checks, score = _collect_system_health_checks()
            SystemSettings.set_setting('system_health_last_run',
                                       {'checks': checks, 'score': score, 'time': datetime.now(timezone.utc).isoformat()},
                                       data_type='json')
            flash('✅ تم تشغيل فحص الصحة تلقائياً', 'success')
        
        return redirect(url_for('advanced.system_health'))
    
    health_checks, overall_health = _collect_system_health_checks()
    return render_template('advanced/system_health.html', 
                         checks=health_checks,
                         overall=overall_health,
                         last_run=SystemSettings.get_setting('system_health_last_run', {}))


def _merge_databases(source_db_path, mode='smart', ignored_tables=None):
    raise ValueError("DB Merger غير مدعوم. النظام يعمل على PostgreSQL فقط.")


def _get_db_size():
    """حجم قاعدة البيانات"""
    try:
        uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if "postgresql" in uri:
            # PostgreSQL size
            try:
                # Extract db name
                db_name = db.engine.url.database
                if not db_name:
                    return 'N/A'
                result = db.session.execute(
                    text("SELECT pg_size_pretty(pg_database_size(:db_name))"),
                    {"db_name": db_name},
                ).scalar()
                return result
            except Exception:
                return 'N/A'
        return 'N/A'
    except Exception:
        return 'N/A'


def _count_all_records():
    """عدد جميع السجلات - محسّن مع cache"""
    cache_key = "total_records_count"
    cached_count = cache.get(cache_key)
    if cached_count is not None:
        return cached_count
    
    try:
        uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if "postgresql" in uri:
            try:
                approx = db.session.execute(
                    text("SELECT COALESCE(SUM(n_live_tup), 0)::bigint FROM pg_stat_user_tables")
                ).scalar()
                approx_val = int(approx or 0)
                cache.set(cache_key, approx_val, timeout=3600)
                return approx_val
            except Exception:
                current_app.logger.warning('cache operation failed silently in advanced_control.py', exc_info=True)

        total = 0
        preparer = db.engine.dialect.identifier_preparer
        inspector = inspect(db.engine)
        tables = [t for t in inspector.get_table_names() if not t.startswith('_alembic') and t != 'alembic_version']
        
        for table in tables:
            try:
                quoted = preparer.quote(table)
                count = db.session.execute(text(f"SELECT COUNT(*) FROM {quoted}")).scalar()
                total += count or 0
            except Exception:
                continue
        cache.set(cache_key, total, timeout=3600)
        return total
    except Exception:
        return 0


def _check_database():
    """فحص قاعدة البيانات"""
    try:
        db.session.execute(text("SELECT 1"))
        return {'name': 'قاعدة البيانات', 'status': 'ok', 'message': 'تعمل بشكل صحيح'}
    except Exception:
        return {'name': 'قاعدة البيانات', 'status': 'error', 'message': 'خطأ في الاتصال'}


def _check_disk_space():
    """فحص المساحة"""
    try:
        import shutil
        total, used, free = shutil.disk_usage(current_app.root_path)
        free_gb = free / (1024**3)
        if free_gb < 1:
            return {'name': 'المساحة', 'status': 'warning', 'message': f'متبقي {free_gb:.2f} GB'}
        return {'name': 'المساحة', 'status': 'ok', 'message': f'متبقي {free_gb:.2f} GB'}
    except Exception:
        return {'name': 'المساحة', 'status': 'unknown', 'message': 'غير معروف'}


def _check_permissions():
    """فحص الصلاحيات"""
    try:
        test_file = os.path.join(current_app.root_path, 'instance', '.test_write')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        return {'name': 'صلاحيات الكتابة', 'status': 'ok', 'message': 'صلاحيات صحيحة'}
    except Exception:
        return {'name': 'صلاحيات الكتابة', 'status': 'error', 'message': 'لا توجد صلاحيات'}


def _check_integrations():
    """فحص التكاملات"""
    integrations_count = SystemSettings.query.filter(
        (SystemSettings.key.like('whatsapp_%')) |
        (SystemSettings.key.like('smtp_%')) |
        (SystemSettings.key.like('reader_%'))
    ).count()
    
    if integrations_count > 0:
        return {'name': 'التكاملات', 'status': 'ok', 'message': f'{integrations_count} تكامل مفعل'}
    return {'name': 'التكاملات', 'status': 'warning', 'message': 'لا توجد تكاملات'}


def _check_performance():
    """فحص الأداء"""
    try:
        start = datetime.now()
        db.session.execute(text("SELECT COUNT(*) FROM users"))
        elapsed = (datetime.now() - start).total_seconds() * 1000
        
        if elapsed < 100:
            return {'name': 'الأداء', 'status': 'ok', 'message': f'{elapsed:.0f}ms'}
        elif elapsed < 500:
            return {'name': 'الأداء', 'status': 'warning', 'message': f'{elapsed:.0f}ms'}
        else:
            return {'name': 'الأداء', 'status': 'error', 'message': f'{elapsed:.0f}ms بطيء'}
    except Exception:
        return {'name': 'الأداء', 'status': 'unknown', 'message': 'غير معروف'}


def _collect_system_health_checks():
    checks = [
        _check_database(),
        _check_disk_space(),
        _check_permissions(),
        _check_integrations(),
        _check_performance(),
    ]
    status_scores = {'ok': 100, 'warning': 65, 'error': 30, 'unknown': 50}
    overall = 0
    if checks:
        overall = sum(status_scores.get(item['status'], 0) for item in checks) / len(checks)
    return checks, round(overall)


def _get_latest_backup_snapshot():
    backup_dir = os.path.join(current_app.root_path, 'instance', 'backups')
    latest = None
    if os.path.exists(backup_dir):
        backups = sorted(
            [
                filename for filename in os.listdir(backup_dir)
                if filename.endswith(('.dump', '.sql'))
            ],
            reverse=True
        )
        if backups:
            filename = backups[0]
            filepath = os.path.join(backup_dir, filename)
            size = os.path.getsize(filepath) / (1024 * 1024)
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            age_hours = (datetime.now() - mtime).total_seconds() / 3600
            latest = {
                'name': filename,
                'size': f'{size:.2f} MB',
                'date': mtime.strftime('%Y-%m-%d %H:%M'),
                'timestamp': mtime.isoformat(),
                'age_hours': round(age_hours, 2),
            }
    return latest or {'name': None, 'size': '0 MB', 'date': None, 'timestamp': None, 'age_hours': None}


def _get_security_snapshot():
    enable_whitelist = SystemSettings.get_setting('enable_ip_whitelist', False)
    enable_blacklist = SystemSettings.get_setting('enable_ip_blacklist', False)
    enable_country_block = SystemSettings.get_setting('enable_country_blocking', False)
    whitelist = _load_json_setting('ip_whitelist', [])
    blacklist = _load_json_setting('ip_blacklist', [])
    blocked_countries = _load_json_setting('blocked_countries', [])
    status = 'ok'
    issues = []
    if enable_whitelist and not whitelist:
        status = 'warning'
        issues.append('whitelist_empty')
    if enable_blacklist and not blacklist:
        status = 'warning'
        issues.append('blacklist_empty')
    if enable_country_block and not blocked_countries:
        status = 'warning'
        issues.append('countries_empty')
    return {
        'status': status,
        'enable_whitelist': enable_whitelist,
        'enable_blacklist': enable_blacklist,
        'enable_country_block': enable_country_block,
        'whitelist_count': len(whitelist),
        'blacklist_count': len(blacklist),
        'country_count': len(blocked_countries),
        'issues': issues,
        'blocked_ips': blacklist[:5],
    }


def _load_json_setting(key, default):
    value = SystemSettings.get_setting(key, None)
    if not value:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _summarize_backup_snapshot(snapshot, auto_backup_enabled):
    summary = {
        'color': 'secondary',
        'message': 'لا توجد بيانات نسخ',
        'status': 'secondary',
        'age_hours': snapshot.get('age_hours'),
    }
    if not snapshot.get('name'):
        summary.update({
            'color': 'danger',
            'status': 'danger',
            'message': 'لا توجد نسخة احتياطية حديثة',
        })
        if not auto_backup_enabled:
            summary['message'] += ' والنسخ التلقائي معطل'
        return summary
    age = snapshot.get('age_hours')
    if age is None:
        summary.update({
            'color': 'secondary',
            'status': 'secondary',
            'message': 'آخر نسخة متاحة (وقت غير معروف)',
        })
    elif age <= 24:
        summary.update({
            'color': 'success',
            'status': 'success',
            'message': 'آخر نسخة خلال 24 ساعة',
        })
    elif age <= 72:
        summary.update({
            'color': 'warning',
            'status': 'warning',
            'message': f'آخر نسخة منذ {int(age)} ساعة',
        })
    else:
        summary.update({
            'color': 'danger',
            'status': 'danger',
            'message': f'آخر نسخة منذ {int(age)} ساعة (قديمة)',
        })
    if not auto_backup_enabled and summary['color'] != 'danger':
        summary['color'] = 'warning'
        summary['status'] = 'warning'
        summary['message'] += ' (النسخ التلقائي معطل)'
    return summary


def _collect_owner_alerts(backup_summary, tenant_stats, security_snapshot, overall_health, auto_backup_enabled, license_info=None):
    alerts = []

    def add_alert(level, title, message, endpoint, icon):
        alerts.append({
            'level': level,
            'title': title,
            'message': message,
            'endpoint': endpoint,
            'icon': icon,
        })

    if backup_summary and backup_summary.get('color') in ('warning', 'danger'):
        add_alert(
            backup_summary['color'],
            'النسخ الاحتياطي',
            backup_summary.get('message'),
            'advanced.backup_manager',
            'database'
        )
    if tenant_stats.get('inactive', 0):
        add_alert(
            'warning',
            'Tenants معطّلة',
            f"{tenant_stats['inactive']} Tenant بحاجة لمراجعة",
            'advanced.multi_tenant',
            'building'
        )
    if security_snapshot.get('issues'):
        add_alert(
            'warning',
            'ضبط الأمان',
            'هناك قوائم أمان ناقصة أو محظورات فارغة',
            'security_control.security_control',
            'shield-alt'
        )
    if overall_health < 80:
        level = 'danger' if overall_health < 60 else 'warning'
        add_alert(
            level,
            'صحة النظام',
            f'درجة الصحة الحالية {overall_health}%',
            'advanced.system_health',
            'heartbeat'
        )
    if license_info and license_info.get('status') in ('warning', 'expired'):
        msg = 'تم انتهاء الترخيص' if license_info['status'] == 'expired' else f"ينتهي خلال {license_info.get('days_left')} يوم"
        add_alert(
            'danger' if license_info['status'] == 'expired' else 'warning',
            'الترخيص',
            msg,
            'advanced.licensing',
            'certificate'
        )
    return alerts[:5]


def _summarize_security_snapshot(snapshot):
    summary = {
        'status': snapshot.get('status', 'unknown'),
        'whitelist_status': 'ok' if snapshot.get('enable_whitelist') and snapshot.get('whitelist_count') else 'warning',
        'blacklist_status': 'ok' if snapshot.get('enable_blacklist') and snapshot.get('blacklist_count') else 'warning',
        'country_status': 'ok' if snapshot.get('enable_country_block') and snapshot.get('country_count') else 'warning',
        'blocked_ips': snapshot.get('blocked_ips', []),
        'issues': snapshot.get('issues', []),
    }
    return summary


def _get_license_status():
    license_setting = SystemSettings.query.filter_by(key='license_info').first()
    if not license_setting or not license_setting.value:
        return None
    info = json.loads(license_setting.value)
    status = 'active'
    days_left = None
    if info.get('expiry'):
        try:
            expiry = datetime.strptime(info['expiry'], '%Y-%m-%d')
            days_left = (expiry - datetime.now(timezone.utc).replace(tzinfo=None)).days
            if days_left <= 0:
                status = 'expired'
            elif days_left <= 30:
                status = 'warning'
        except Exception:
            status = 'unknown'
    info['status'] = status
    info['days_left'] = days_left
    return info


def _handle_db_merger_preview():
    flash('❌ DB Merger غير مدعوم. النظام يعمل على PostgreSQL فقط.', 'danger')
    return redirect(url_for('advanced.backup_manager'))


def _handle_db_merger_execute():
    flash('❌ DB Merger غير مدعوم. النظام يعمل على PostgreSQL فقط.', 'danger')
    return redirect(url_for('advanced.backup_manager'))


def _compare_databases(source_db_path, ignored_tables):
    raise ValueError("DB Merger غير مدعوم. النظام يعمل على PostgreSQL فقط.")


def _create_safety_backup():
    """Create a safety backup before merging databases using the centralized backup function."""
    try:
        from extensions import perform_backup_db
        success, message, filepath = perform_backup_db(current_app)
        if success and filepath:
            return os.path.basename(filepath)
        else:
            current_app.logger.error(f"Safety backup failed: {message}")
            return None
    except Exception as e:
        current_app.logger.error(f"Safety backup exception: {e}")
        return None


def _log_owner_action(action, target=None, meta=None):
    entry = {
        'action': action,
        'target': target,
        'meta': meta or {},
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'user': {
            'id': getattr(current_user, 'id', None),
            'username': getattr(current_user, 'username', None),
        }
    }
    try:
        history = SystemSettings.get_setting('owner_action_log', [])
        if not isinstance(history, list):
            history = []
        history.insert(0, entry)
        history = history[:100]
        SystemSettings.set_setting(
            'owner_action_log',
            history,
            description='Owner critical actions log',
            data_type='json',
            is_public=False
        )
    except Exception as exc:
        current_app.logger.warning('Failed to log owner action %s: %s', action, exc)


def _record_backup_failure(message):
    try:
        failures = SystemSettings.get_setting('backup_failures', [])
        if not isinstance(failures, list):
            failures = []
        failures.insert(0, {
            'message': message,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        failures = failures[:5]
        SystemSettings.set_setting(
            'backup_failures',
            failures,
            description='Recent backup failures',
            data_type='json',
            is_public=False
        )
    except Exception as exc:
        current_app.logger.warning('Failed to record backup failure: %s', exc)


def _load_smoke_checklist_state():
    try:
        state = SystemSettings.get_setting('owner_smoke_checklist', {})
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    completed = state.get('completed', [])
    if not isinstance(completed, list):
        completed = []
    return {
        'completed': completed,
        'timestamp': state.get('timestamp'),
    }


def _validate_safe_slug(value):
    if not value:
        return False
    allowed = set(string.ascii_letters + string.digits + '_-')
    return all(ch in allowed for ch in value)

def _make_tenant_schema_name(slug):
    slug = (slug or '').strip().lower().replace('-', '_')
    cleaned = ''.join(ch for ch in slug if (ch.isalnum() or ch == '_'))
    if not cleaned:
        return None
    if cleaned[0].isdigit():
        cleaned = f"t{cleaned}"
    schema_name = f"t_{cleaned}"
    return schema_name[:63]


def _validate_time_string(value):
    try:
        datetime.strptime(value, '%H:%M')
        return True
    except Exception:
        return False


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_numeric(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _describe_schedule_status(enabled, schedule_info):
    if not enabled:
        return {
            'text': 'معطلة',
            'color': 'secondary',
            'next_run': None,
            'type': None,
            'time': None,
        }
    schedule_type = schedule_info.get('type', 'daily')
    schedule_time = schedule_info.get('time', '03:00')
    label = SCHEDULE_LABELS.get(schedule_type, schedule_type)
    next_run = _estimate_next_run(schedule_type, schedule_time)
    return {
        'text': f'{label} - {schedule_time}',
        'color': 'success',
        'next_run': next_run,
        'type': schedule_type,
        'time': schedule_time,
    }


def _estimate_next_run(schedule_type, schedule_time):
    now = datetime.now()
    if schedule_type == 'hourly':
        return (now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
    try:
        hours, minutes = schedule_time.split(':')
        target = now.replace(hour=int(hours), minute=int(minutes), second=0, microsecond=0)
    except Exception:
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= now:
        if schedule_type == 'daily':
            target += timedelta(days=1)
        elif schedule_type == 'weekly':
            target += timedelta(days=7)
        elif schedule_type == 'monthly':
            target += timedelta(days=30)
        else:
            target += timedelta(days=1)
    return target.strftime('%Y-%m-%d %H:%M')


def _build_backup_summary(backups):
    if not backups:
        return {
            'status': 'danger',
            'color': 'danger',
            'message': 'لا توجد نسخة احتياطية متاحة',
            'recommendation': 'أنشئ نسخة احتياطية جديدة الآن.',
            'last_backup': None,
            'age_hours': None,
        }
    last_backup = backups[0]
    age_hours = last_backup.get('age_hours', 0)
    if age_hours <= 24:
        status = ('success', 'سليم خلال آخر 24 ساعة')
    elif age_hours <= 72:
        status = ('warning', 'آخر نسخة أقدم من 24 ساعة')
    else:
        status = ('danger', 'آخر نسخة قديمة جداً')
    color = status[0]
    message = status[1]
    recommendation = 'ينصح بإنشاء نسخة اليوم.' if color != 'success' else 'الوضع آمن حالياً.'
    return {
        'status': color,
        'color': color,
        'message': message,
        'recommendation': recommendation,
        'last_backup': last_backup,
        'age_hours': age_hours,
    }


ACCOUNTING_REPORT_TEMPLATE = """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="utf-8">
    <title>تقرير التحكم المحاسبي</title>
    <style>
        body { font-family: "Amiri", "Cairo", sans-serif; margin: 40px; color: #111; }
        h1, h2, h3 { color: #1a237e; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
        th, td { border: 1px solid #ccc; padding: 8px 10px; text-align: right; }
        th { background: #f3f6ff; }
        .section { margin-bottom: 30px; }
        ul { padding-right: 18px; }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }
        .card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; background: #fafafa; }
    </style>
</head>
<body>
    <header class="section">
        <h1>تقرير التحكم المحاسبي</h1>
        <p>تاريخ الإصدار: {{ generated_at.strftime('%Y-%m-%d %H:%M') }} UTC</p>
    </header>
    <section class="section">
        <h2>الملخص التنفيذي</h2>
        <table>
            <tr>
                <th>الحسابات البنكية</th>
                <th>مراكز التكلفة</th>
                <th>المشاريع</th>
                <th>التنبيهات</th>
            </tr>
            <tr>
                <td>{{ stats.total_bank_accounts }} / {{ stats.active_bank_accounts }} نشطة</td>
                <td>{{ stats.total_cost_centers }} / {{ stats.active_cost_centers }} نشطة</td>
                <td>{{ stats.total_projects }} / {{ stats.active_projects }} نشطة</td>
                <td>{{ stats.alert_count }}</td>
            </tr>
        </table>
    </section>
    <section class="section">
        <h2>مقتطفات الإعدادات</h2>
        <div class="grid">
            <div class="card">
                <h3>البنوك</h3>
                <ul>
                    <li>التسويات البنكية: {{ 'مفعلة' if settings.bank.enable_bank_reconciliation else 'معطلة' }}</li>
                    <li>موافقة البنك: {{ 'مطَلوبة' if settings.bank.require_bank_approval else 'اختيارية' }}</li>
                    <li>موافقة المالك: {{ 'مطَلوبة' if settings.bank.owner_approval_required else 'اختيارية' }}</li>
                    <li>نسبة التسامح: {{ (settings.bank.auto_match_tolerance * 100)|round(2) }}%</li>
                    <li>حد المعاملة الكبيرة: {{ settings.bank.large_transaction_threshold|int }} ₪</li>
                </ul>
            </div>
            <div class="card">
                <h3>مراكز التكلفة</h3>
                <ul>
                    <li>التفعيل: {{ 'مفعل' if settings.cost_centers.enable_cost_centers else 'معطل' }}</li>
                    <li>إلزامية التحديد: {{ 'مطلوبة' if settings.cost_centers.require_cost_center else 'اختيارية' }}</li>
                    <li>حد التحذير: {{ settings.cost_centers.budget_warning_threshold }}%</li>
                    <li>حد الخطر: {{ settings.cost_centers.budget_danger_threshold }}%</li>
                    <li>حد المنع: {{ settings.cost_centers.budget_block_threshold }}%</li>
                </ul>
            </div>
            <div class="card">
                <h3>المشاريع</h3>
                <ul>
                    <li>تفعيل الوحدة: {{ 'مفعلة' if settings.projects.enable_projects else 'معطلة' }}</li>
                    <li>ربط تلقائي: {{ 'مفعل' if settings.projects.auto_link_transactions else 'معطل' }}</li>
                    <li>حد الانحراف: {{ settings.projects.project_variance_threshold }}%</li>
                    <li>تنبيهات التكلفة: {{ 'مفعلة' if settings.projects.cost_overrun_alerts else 'معطلة' }}</li>
                    <li>تنبيهات التأخير: {{ 'مفعلة' if settings.projects.delay_alerts else 'معطلة' }}</li>
                </ul>
            </div>
            <div class="card">
                <h3>الأتمتة والأمان</h3>
                <ul>
                    <li>الترحيل التلقائي: {{ 'مفعل' if settings.automation.auto_gl_posting else 'معطل' }}</li>
                    <li>تحليل AI: {{ 'مفعل' if settings.automation.ai_transaction_analysis else 'معطل' }}</li>
                    <li>النسخ الاحتياطي اليومي: {{ 'مفعل' if settings.automation.auto_daily_backup else 'معطل' }} عند {{ settings.automation.backup_time }}</li>
                    <li>سجل التدقيق الكامل: {{ 'مفعل دائماً' }}</li>
                    <li>قفل السجلات القديمة: {{ 'مفعل' if settings.security.lock_old_records else 'معطل' }} بعد {{ settings.security.lock_period_days }} يوم</li>
                </ul>
            </div>
        </div>
    </section>
    <section class="section">
        <h2>فحص النظام</h2>
        <table>
            <tr>
                <th>المعاملات غير المطابقة</th>
                <th>تسويات قيد الموافقة</th>
                <th>مراكز متجاوزة للميزانية</th>
                <th>مشاريع متأخرة</th>
            </tr>
            <tr>
                <td>{{ diagnostics.unmatched_transactions }}</td>
                <td>{{ diagnostics.pending_reconciliations }}</td>
                <td>{{ diagnostics.over_budget_centers }}</td>
                <td>{{ diagnostics.delayed_projects }}</td>
            </tr>
        </table>
        <h3>أقرب المواعيد</h3>
        <ul>
            {% for project in diagnostics.upcoming_projects %}
            <li>{{ project.code }} - {{ project.name }} ({{ project.end_date }})</li>
            {% else %}
            <li>لا توجد مواعيد قريبة.</li>
            {% endfor %}
        </ul>
        <h3>آخر عمليات التدقيق</h3>
        <ul>
            {% for audit in diagnostics.recent_audit %}
            <li>{{ audit['created_at'] }} - {{ audit['action'] }} بواسطة {{ audit['user'] or 'System' }}</li>
            {% else %}
            <li>لا توجد بيانات متاحة.</li>
            {% endfor %}
        </ul>
    </section>
    <section class="section">
        <h2>التوصيات</h2>
        <ul>
            {% for note in diagnostics.recommendations %}
            <li>{{ note }}</li>
            {% else %}
            <li>لا توجد توصيات ملحة حالياً.</li>
            {% endfor %}
        </ul>
        <p>آخر نسخة احتياطية: {{ diagnostics.backup_status.latest_backup.date if diagnostics.backup_status.latest_backup else 'غير متوفرة' }}</p>
    </section>
</body>
</html>
"""


def _source_has_key(source, key):
    try:
        return key in source
    except TypeError:
        return False


def _setting_value(source, key, base, default, preserve_missing):
    if _source_has_key(source, key):
        return source.get(key)
    if preserve_missing and base:
        return base.get(key, default)
    return default


def _to_bool_flag(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ('1', 'true', 'on', 'yes')


def _infer_setting_type(value):
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    return 'string'


def _persist_settings_dict(settings):
    for key, value in settings.items():
        SystemSettings.set_setting(key, value, data_type=_infer_setting_type(value), commit=False)


def _normalize_bank_settings(source, base=None, preserve_missing=False):
    if base is None:
        base = _get_accounting_settings_bundle()['bank']
    tolerance_default = base.get('auto_match_tolerance', 0.01)
    tolerance_raw = _setting_value(source, 'auto_match_tolerance', base, tolerance_default, preserve_missing)
    tolerance = _clamp_numeric(_to_float(tolerance_raw, tolerance_default), 0, 1)
    match_default = base.get('match_date_range', 3)
    match_raw = _setting_value(source, 'match_date_range', base, match_default, preserve_missing)
    match_range = int(_clamp_numeric(_to_float(match_raw, match_default), 1, 30))
    large_default = base.get('large_transaction_threshold', 50000)
    large_raw = _setting_value(source, 'large_transaction_threshold', base, large_default, preserve_missing)
    large_threshold = _clamp_numeric(_to_float(large_raw, large_default), 0, 1_000_000_000)
    charges_default = base.get('bank_charges_account', '601000')
    charges_raw = _setting_value(source, 'bank_charges_account', base, charges_default, preserve_missing)
    interest_default = base.get('bank_interest_account', '401500')
    interest_raw = _setting_value(source, 'bank_interest_account', base, interest_default, preserve_missing)
    return {
        'enable_bank_reconciliation': _to_bool_flag(_setting_value(source, 'enable_bank_reconciliation', base, False if not preserve_missing else base.get('enable_bank_reconciliation', False), preserve_missing)),
        'auto_match_tolerance': tolerance,
        'require_bank_approval': _to_bool_flag(_setting_value(source, 'require_bank_approval', base, False if not preserve_missing else base.get('require_bank_approval', False), preserve_missing)),
        'match_date_range': match_range,
        'bank_charges_account': (str(charges_raw or charges_default).strip() or charges_default),
        'bank_interest_account': (str(interest_raw or interest_default).strip() or interest_default),
        'alert_large_transactions': _to_bool_flag(_setting_value(source, 'alert_large_transactions', base, False if not preserve_missing else base.get('alert_large_transactions', True), preserve_missing)),
        'large_transaction_threshold': large_threshold,
        'owner_approval_required': _to_bool_flag(_setting_value(source, 'owner_approval_required', base, False if not preserve_missing else base.get('owner_approval_required', True), preserve_missing)),
    }


def _normalize_cost_center_settings(source, base=None, preserve_missing=False):
    if base is None:
        base = _get_accounting_settings_bundle()['cost_centers']
    warn_default = base.get('budget_warning_threshold', 80)
    warn_raw = _setting_value(source, 'budget_warning_threshold', base, warn_default, preserve_missing)
    warn_threshold = int(_clamp_numeric(_to_float(warn_raw, warn_default), 50, 100))
    danger_default = base.get('budget_danger_threshold', 95)
    danger_raw = _setting_value(source, 'budget_danger_threshold', base, danger_default, preserve_missing)
    danger_threshold = int(_clamp_numeric(_to_float(danger_raw, danger_default), 80, 100))
    block_default = base.get('budget_block_threshold', 100)
    block_raw = _setting_value(source, 'budget_block_threshold', base, block_default, preserve_missing)
    block_threshold = int(_clamp_numeric(_to_float(block_raw, block_default), 90, 120))
    expense_default = base.get('default_expense_account', '501000')
    expense_raw = _setting_value(source, 'default_expense_account', base, expense_default, preserve_missing)
    return {
        'enable_cost_centers': _to_bool_flag(_setting_value(source, 'enable_cost_centers', base, False if not preserve_missing else base.get('enable_cost_centers', False), preserve_missing)),
        'require_cost_center': _to_bool_flag(_setting_value(source, 'require_cost_center', base, False if not preserve_missing else base.get('require_cost_center', False), preserve_missing)),
        'allow_hierarchy': _to_bool_flag(_setting_value(source, 'allow_hierarchy', base, True if preserve_missing else False, preserve_missing)),
        'budget_warning_threshold': warn_threshold,
        'budget_danger_threshold': danger_threshold,
        'budget_block_threshold': block_threshold,
        'allow_over_budget': _to_bool_flag(_setting_value(source, 'allow_over_budget', base, False if not preserve_missing else base.get('allow_over_budget', False), preserve_missing)),
        'auto_allocate': _to_bool_flag(_setting_value(source, 'auto_allocate', base, True if preserve_missing else False, preserve_missing)),
        'default_expense_account': (str(expense_raw or expense_default).strip() or expense_default),
    }


def _normalize_project_settings(source, base=None, preserve_missing=False):
    if base is None:
        base = _get_accounting_settings_bundle()['projects']
    variance_default = base.get('project_variance_threshold', 10)
    variance_raw = _setting_value(source, 'project_variance_threshold', base, variance_default, preserve_missing)
    variance = _clamp_numeric(_to_float(variance_raw, variance_default), 5, 50)
    prefix_default = base.get('project_numbering_prefix', 'PRJ')
    prefix_raw = _setting_value(source, 'project_numbering_prefix', base, prefix_default, preserve_missing)
    revenue_default = base.get('projects_revenue_account', '401000')
    revenue_raw = _setting_value(source, 'projects_revenue_account', base, revenue_default, preserve_missing)
    cost_default = base.get('projects_cost_account', '501000')
    cost_raw = _setting_value(source, 'projects_cost_account', base, cost_default, preserve_missing)
    return {
        'enable_projects': _to_bool_flag(_setting_value(source, 'enable_projects', base, False if not preserve_missing else base.get('enable_projects', False), preserve_missing)),
        'auto_link_transactions': _to_bool_flag(_setting_value(source, 'auto_link_transactions', base, True if preserve_missing else False, preserve_missing)),
        'project_numbering_prefix': (str(prefix_raw or prefix_default).strip() or prefix_default),
        'project_variance_threshold': variance,
        'projects_revenue_account': (str(revenue_raw or revenue_default).strip() or revenue_default),
        'projects_cost_account': (str(cost_raw or cost_default).strip() or cost_default),
        'auto_phase_tracking': _to_bool_flag(_setting_value(source, 'auto_phase_tracking', base, True if preserve_missing else False, preserve_missing)),
        'cost_overrun_alerts': _to_bool_flag(_setting_value(source, 'cost_overrun_alerts', base, True if preserve_missing else False, preserve_missing)),
        'delay_alerts': _to_bool_flag(_setting_value(source, 'delay_alerts', base, True if preserve_missing else False, preserve_missing)),
    }


def _normalize_automation_settings(source, base=None, preserve_missing=False):
    if base is None:
        base = _get_accounting_settings_bundle()['automation']
    backup_time_default = base.get('backup_time', '02:00')
    backup_time_raw = _setting_value(source, 'backup_time', base, backup_time_default, preserve_missing)
    backup_time = str(backup_time_raw or backup_time_default)
    if not _validate_time_string(backup_time):
        backup_time = backup_time_default
    return {
        'auto_gl_posting': _to_bool_flag(_setting_value(source, 'auto_gl_posting', base, True if preserve_missing else False, preserve_missing)),
        'ai_transaction_analysis': _to_bool_flag(_setting_value(source, 'ai_transaction_analysis', base, False if not preserve_missing else base.get('ai_transaction_analysis', False), preserve_missing)),
        'smart_matching_suggestions': _to_bool_flag(_setting_value(source, 'smart_matching_suggestions', base, True if preserve_missing else False, preserve_missing)),
        'auto_daily_backup': _to_bool_flag(_setting_value(source, 'auto_daily_backup', base, True if preserve_missing else False, preserve_missing)),
        'backup_time': backup_time,
    }


def _normalize_security_settings(source, base=None, preserve_missing=False):
    if base is None:
        base = _get_accounting_settings_bundle()['security']
    lock_default = base.get('lock_period_days', 30)
    lock_raw = _setting_value(source, 'lock_period_days', base, lock_default, preserve_missing)
    lock_days = int(_clamp_numeric(_to_float(lock_raw, lock_default), 7, 365))
    audit_default = base.get('audit_retention_days', 365)
    audit_raw = _setting_value(source, 'audit_retention_days', base, audit_default, preserve_missing)
    audit_days = int(_clamp_numeric(_to_float(audit_raw, audit_default), 30, 3650))
    full_audit = _setting_value(source, 'full_audit_trail', base, True, preserve_missing)
    return {
        'full_audit_trail': True if full_audit is None else _to_bool_flag(full_audit),
        'track_modifications': _to_bool_flag(_setting_value(source, 'track_modifications', base, True if preserve_missing else False, preserve_missing)),
        'security_alerts': _to_bool_flag(_setting_value(source, 'security_alerts', base, True if preserve_missing else False, preserve_missing)),
        'lock_old_records': _to_bool_flag(_setting_value(source, 'lock_old_records', base, False if not preserve_missing else base.get('lock_old_records', False), preserve_missing)),
        'lock_period_days': lock_days,
        'audit_retention_days': audit_days,
    }


def _save_bank_settings(source, base=None, preserve_missing=False):
    settings = _normalize_bank_settings(source, base, preserve_missing)
    _persist_settings_dict(settings)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        flash('حدث خطأ أثناء الحفظ', 'danger')
    return settings


def _save_cost_center_settings(source, base=None, preserve_missing=False):
    settings = _normalize_cost_center_settings(source, base, preserve_missing)
    _persist_settings_dict(settings)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        flash('حدث خطأ أثناء الحفظ', 'danger')
    return settings


def _save_project_settings(source, base=None, preserve_missing=False):
    settings = _normalize_project_settings(source, base, preserve_missing)
    _persist_settings_dict(settings)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        flash('حدث خطأ أثناء الحفظ', 'danger')
    return settings


def _save_automation_settings(source, base=None, preserve_missing=False):
    settings = _normalize_automation_settings(source, base, preserve_missing)
    _persist_settings_dict(settings)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        flash('حدث خطأ أثناء الحفظ', 'danger')
    return settings


def _save_security_settings(source, base=None, preserve_missing=False):
    settings = _normalize_security_settings(source, base, preserve_missing)
    _persist_settings_dict(settings)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('commit error')
        flash('حدث خطأ أثناء الحفظ', 'danger')
    return settings


def _get_accounting_settings_bundle():
    bank_settings = {
        'enable_bank_reconciliation': SystemSettings.get_setting('enable_bank_reconciliation', False),
        'auto_match_tolerance': float(SystemSettings.get_setting('auto_match_tolerance', 0.01)),
        'require_bank_approval': SystemSettings.get_setting('require_bank_approval', True),
        'match_date_range': int(SystemSettings.get_setting('match_date_range', 3)),
        'bank_charges_account': SystemSettings.get_setting('bank_charges_account', '601000'),
        'bank_interest_account': SystemSettings.get_setting('bank_interest_account', '401500'),
        'alert_large_transactions': SystemSettings.get_setting('alert_large_transactions', True),
        'large_transaction_threshold': float(SystemSettings.get_setting('large_transaction_threshold', 50000)),
        'owner_approval_required': SystemSettings.get_setting('owner_approval_required', True),
    }
    cost_center_settings = {
        'enable_cost_centers': SystemSettings.get_setting('enable_cost_centers', False),
        'require_cost_center': SystemSettings.get_setting('require_cost_center', False),
        'allow_hierarchy': SystemSettings.get_setting('allow_hierarchy', True),
        'budget_warning_threshold': int(SystemSettings.get_setting('budget_warning_threshold', 80)),
        'budget_danger_threshold': int(SystemSettings.get_setting('budget_danger_threshold', 95)),
        'budget_block_threshold': int(SystemSettings.get_setting('budget_block_threshold', 100)),
        'allow_over_budget': SystemSettings.get_setting('allow_over_budget', False),
        'auto_allocate': SystemSettings.get_setting('auto_allocate', True),
        'default_expense_account': SystemSettings.get_setting('default_expense_account', '501000'),
    }
    project_settings = {
        'enable_projects': SystemSettings.get_setting('enable_projects', False),
        'auto_link_transactions': SystemSettings.get_setting('auto_link_transactions', True),
        'project_numbering_prefix': SystemSettings.get_setting('project_numbering_prefix', 'PRJ'),
        'project_variance_threshold': float(SystemSettings.get_setting('project_variance_threshold', 10)),
        'projects_revenue_account': SystemSettings.get_setting('projects_revenue_account', '401000'),
        'projects_cost_account': SystemSettings.get_setting('projects_cost_account', '501000'),
        'auto_phase_tracking': SystemSettings.get_setting('auto_phase_tracking', True),
        'cost_overrun_alerts': SystemSettings.get_setting('cost_overrun_alerts', True),
        'delay_alerts': SystemSettings.get_setting('delay_alerts', True),
    }
    automation_settings = {
        'auto_gl_posting': SystemSettings.get_setting('auto_gl_posting', True),
        'ai_transaction_analysis': SystemSettings.get_setting('ai_transaction_analysis', False),
        'smart_matching_suggestions': SystemSettings.get_setting('smart_matching_suggestions', True),
        'auto_daily_backup': SystemSettings.get_setting('auto_daily_backup', True),
        'backup_time': SystemSettings.get_setting('backup_time', '02:00'),
    }
    security_settings = {
        'full_audit_trail': SystemSettings.get_setting('full_audit_trail', True),
        'track_modifications': SystemSettings.get_setting('track_modifications', True),
        'security_alerts': SystemSettings.get_setting('security_alerts', True),
        'lock_old_records': SystemSettings.get_setting('lock_old_records', False),
        'lock_period_days': int(SystemSettings.get_setting('lock_period_days', 30)),
        'audit_retention_days': int(SystemSettings.get_setting('audit_retention_days', 365)),
    }
    return {
        'bank': bank_settings,
        'cost_centers': cost_center_settings,
        'projects': project_settings,
        'automation': automation_settings,
        'security': security_settings,
    }


def _calculate_accounting_overview(settings_bundle=None):
    from models import BankAccount, CostCenter, Project
    if settings_bundle is None:
        settings_bundle = _get_accounting_settings_bundle()
    total_bank_accounts = BankAccount.query.count()
    active_bank_accounts = BankAccount.query.filter_by(is_active=True).count()
    total_cost_centers = CostCenter.query.count()
    active_cost_centers = CostCenter.query.filter_by(is_active=True).count()
    total_budget = db.session.query(func.sum(CostCenter.budget_amount)).filter_by(is_active=True).scalar() or 0
    total_projects = Project.query.count()
    active_projects = Project.query.filter(Project.status == 'ACTIVE').count()
    alerts = 0
    if not settings_bundle['bank']['enable_bank_reconciliation']:
        alerts += 1
    if not settings_bundle['cost_centers']['enable_cost_centers']:
        alerts += 1
    if not settings_bundle['projects']['enable_projects']:
        alerts += 1
    return {
        'total_bank_accounts': total_bank_accounts,
        'active_bank_accounts': active_bank_accounts,
        'total_cost_centers': total_cost_centers,
        'active_cost_centers': active_cost_centers,
        'total_projects': total_projects,
        'active_projects': active_projects,
        'alert_count': alerts,
        'total_budget': float(total_budget),
    }


def _run_accounting_system_check():
    from models import BankTransaction, CostCenter, Project, BankReconciliation, AuditLog
    from sqlalchemy import func
    today = date.today()
    unmatched = BankTransaction.query.filter_by(matched=False).count()
    pending_reconciliations = BankReconciliation.query.filter(BankReconciliation.status != 'APPROVED').count()
    over_budget = db.session.query(func.count(CostCenter.id)).filter(CostCenter.actual_amount > CostCenter.budget_amount, CostCenter.is_active == True).scalar() or 0
    delayed_projects = Project.query.filter(
        Project.status.in_(('PLANNED', 'ACTIVE', 'ON_HOLD')),
        Project.planned_end_date.isnot(None),
        Project.planned_end_date < today
    ).count()
    upcoming = Project.query.filter(
        Project.status == 'ACTIVE',
        Project.end_date.isnot(None),
        Project.end_date >= today
    ).order_by(Project.end_date.asc()).limit(3).all()
    upcoming_projects = [
        {
            'code': proj.code,
            'name': proj.name,
            'end_date': proj.end_date.strftime('%Y-%m-%d') if proj.end_date else None,
        }
        for proj in upcoming
    ]
    recent_audit_rows = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(5).all()
    recent_audit = [
        {
            'action': row.action,
            'user_id': row.user_id,
            'created_at': row.created_at.strftime('%Y-%m-%d %H:%M'),
        }
        for row in recent_audit_rows
    ]
    backup_manager = AutomatedBackupManager(current_app._get_current_object())
    backup_status = backup_manager.get_backup_status()
    latest_backup = backup_status.get('latest_backup')
    if latest_backup and isinstance(latest_backup.get('date'), datetime):
        backup_status['latest_backup']['date'] = latest_backup['date'].strftime('%Y-%m-%d %H:%M')
    recommendations = []
    if unmatched:
        recommendations.append(f'يوجد {unmatched} معاملة بنكية غير مطابقة.')
    if over_budget:
        recommendations.append(f'{over_budget} مركز تكلفة تجاوز الميزانية المحددة.')
    if delayed_projects:
        recommendations.append(f'{delayed_projects} مشروع يحتاج مراجعة الجدول الزمني.')
    if not latest_backup:
        recommendations.append('لا توجد نسخة احتياطية حديثة، يرجى إنشاء نسخة فوراً.')
    return {
        'unmatched_transactions': unmatched,
        'pending_reconciliations': pending_reconciliations,
        'over_budget_centers': over_budget,
        'delayed_projects': delayed_projects,
        'upcoming_projects': upcoming_projects,
        'recent_audit': recent_audit,
        'backup_status': backup_status,
        'recommendations': recommendations,
    }


@advanced_bp.route('/download-cloned-system/<clone_name>')
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def download_cloned_system(clone_name):
    """تحميل نظام مستنسخ"""
    if not _validate_safe_slug(clone_name):
        flash('❌ اسم النسخة غير صالح', 'danger')
        return redirect(url_for('advanced.system_cloner'))
    try:
        import zipfile
        from io import BytesIO
        
        clone_dir = os.path.join(current_app.root_path, 'instance', 'clones', secure_filename(clone_name))
        
        if not os.path.exists(clone_dir):
            flash('❌ النظام غير موجود', 'danger')
            return redirect(url_for('advanced.system_cloner'))
        
                              
        memory_file = BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(clone_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, clone_dir)
                    zipf.write(file_path, arcname)
        
        memory_file.seek(0)
        
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{clone_name}.zip'
        )
        
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('advanced.system_cloner'))


@advanced_bp.route('/system-cloner', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_CONFIG)
def system_cloner():
    """مولد الأنظمة المخصصة - استنساخ ذكي للمزايا المختارة"""
    
    available_modules = {
        'core': {
            'name': 'النواة الأساسية',
            'description': 'المستخدمين + الصلاحيات + الإعدادات',
            'required': True,
            'files': {
                'models': ['User', 'Role', 'Permission', 'SystemSettings'],
                'routes': ['auth', 'main', 'users', 'roles', 'permissions'],
                'templates': ['base.html', 'dashboard.html', 'auth/*', 'users/*'],
                'static': ['css/style.css', 'js/app.js']
            }
        },
        'customers': {
            'name': 'إدارة العملاء',
            'description': 'العملاء + كشوف الحساب',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': ['Customer'],
                'routes': ['customers'],
                'templates': ['customers/*'],
                'static': []
            }
        },
        'sales': {
            'name': 'المبيعات',
            'description': 'فواتير المبيعات + الأصناف',
            'required': False,
            'dependencies': ['core', 'customers'],
            'files': {
                'models': ['Sale', 'SaleLine', 'Product'],
                'routes': ['sales'],
                'templates': ['sales/*'],
                'static': ['css/sales.css']
            }
        },
        'service': {
            'name': 'الصيانة',
            'description': 'طلبات الصيانة + القطع',
            'required': False,
            'dependencies': ['core', 'customers'],
            'files': {
                'models': ['ServiceRequest', 'ServicePart', 'ServiceTask'],
                'routes': ['service'],
                'templates': ['service/*'],
                'static': ['css/service.css']
            }
        },
        'warehouses': {
            'name': 'المستودعات',
            'description': 'المخزون + الحجوزات',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': ['Warehouse', 'StockLevel', 'PreOrder'],
                'routes': ['warehouses', 'parts'],
                'templates': ['warehouses/*', 'parts/*'],
                'static': ['css/warehouses.css']
            }
        },
        'payments': {
            'name': 'الدفعات',
            'description': 'الدفعات + الشيكات',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': ['Payment', 'PaymentSplit', 'Check'],
                'routes': ['payments', 'checks'],
                'templates': ['payments/*', 'checks/*'],
                'static': []
            }
        },
        'expenses': {
            'name': 'النفقات',
            'description': 'المصروفات + الموظفين',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': ['Expense', 'ExpenseType', 'Employee'],
                'routes': ['expenses'],
                'templates': ['expenses/*'],
                'static': []
            }
        },
        'vendors': {
            'name': 'الموردين والشركاء',
            'description': 'الموردين + الشركاء + التسويات',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': ['Supplier', 'Partner', 'SupplierSettlement', 'PartnerSettlement'],
                'routes': ['vendors', 'supplier_settlements', 'partner_settlements'],
                'templates': ['vendors/*'],
                'static': []
            }
        },
        'shipments': {
            'name': 'الشحنات',
            'description': 'الشحنات + البنود',
            'required': False,
            'dependencies': ['core', 'warehouses', 'vendors'],
            'files': {
                'models': ['Shipment', 'ShipmentItem', 'ShipmentPartner'],
                'routes': ['shipments'],
                'templates': ['shipments/*'],
                'static': ['css/shipments.css']
            }
        },
        'ledger': {
            'name': 'دفتر الأستاذ',
            'description': 'المحاسبة + القيود',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': ['GLBatch', 'GLEntry', 'Account'],
                'routes': ['ledger_blueprint'],                                                        
                'templates': ['ledger/*'],
                'static': []
            }
        },
        'shop': {
            'name': 'المتجر الإلكتروني',
            'description': 'المتجر + السلة + الطلبات',
            'required': False,
            'dependencies': ['core', 'customers', 'sales', 'warehouses'],
            'files': {
                'models': ['OnlineCart', 'OnlineCartItem', 'OnlinePreOrder', 'OnlinePayment'],
                'routes': ['shop'],
                'templates': ['shop/*'],
                'static': ['css/shop.css']
            }
        },
        'reports': {
            'name': 'التقارير',
            'description': 'تقارير شاملة',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': [],
                'routes': ['report_routes', 'admin_reports'],
                'templates': ['reports/*', 'admin/reports/*'],
                'static': ['css/reporting.css']
            }
        },
        'currencies': {
            'name': 'العملات',
            'description': 'أسعار الصرف',
            'required': False,
            'dependencies': ['core'],
            'files': {
                'models': ['Currency', 'ExchangeRate'],
                'routes': ['currencies'],
                'templates': ['currencies/*'],
                'static': []
            }
        },
    }
    
    if request.method == 'POST':
        selected_modules = request.form.getlist('modules')
        clone_name = request.form.get('clone_name', 'custom_system')
        if not _validate_safe_slug(clone_name):
            flash('❌ اسم النسخة يجب أن يكون بدون مسافات أو رموز خاصة', 'danger')
            return redirect(url_for('advanced.system_cloner'))
        
        try:
            result = _clone_system(selected_modules, clone_name, available_modules)
            
            flash(f'✅ تم إنشاء النظام المخصص: {clone_name}', 'success')
            flash(f'📦 الملفات: {result["files_count"]} ملف', 'info')
            flash(f'📍 الموقع: {result["output_path"]}', 'info')
            
                                            
            return redirect(url_for('advanced.system_cloner', download=clone_name))
            
        except Exception as e:
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
            return redirect(url_for('advanced.system_cloner'))
    
                           
    clones_dir = os.path.join(current_app.root_path, 'instance', 'clones')
    cloned_systems = []
    if os.path.exists(clones_dir):
        for name in os.listdir(clones_dir):
            clone_path = os.path.join(clones_dir, name)
            if os.path.isdir(clone_path):
                                 
                total_size = sum(
                    os.path.getsize(os.path.join(dirpath, filename))
                    for dirpath, dirnames, filenames in os.walk(clone_path)
                    for filename in filenames
                )
                cloned_systems.append({
                    'name': name,
                    'size': f'{total_size / (1024 * 1024):.2f} MB',
                    'created': datetime.fromtimestamp(os.path.getctime(clone_path)).strftime('%Y-%m-%d %H:%M')
                })
    
    download_ready = request.args.get('download')
    
    return render_template('advanced/system_cloner.html', 
                         modules=available_modules,
                         cloned_systems=cloned_systems,
                         download_ready=download_ready)


def _clone_system(selected_modules, clone_name, available_modules):
    """استنساخ النظام بالمزايا المختارة"""
    
    modules_to_clone = set(selected_modules)
    modules_to_clone.add('core')
    
    for module_key in list(modules_to_clone):
        module = available_modules.get(module_key)
        if module and 'dependencies' in module:
            modules_to_clone.update(module['dependencies'])
    
    output_dir = os.path.join(current_app.root_path, 'instance', 'clones', clone_name)
    os.makedirs(output_dir, exist_ok=True)
    
    files_copied = 0
    
    for module_key in modules_to_clone:
        module = available_modules.get(module_key)
        if not module:
            continue
        
        files = module.get('files', {})
        
        for route in files.get('routes', []):
            src = os.path.join(current_app.root_path, 'routes', f'{route}.py')
            if os.path.exists(src):
                dst_dir = os.path.join(output_dir, 'routes')
                os.makedirs(dst_dir, exist_ok=True)
                shutil.copy2(src, os.path.join(dst_dir, f'{route}.py'))
                files_copied += 1
        
        for template_pattern in files.get('templates', []):
            if '*' in template_pattern:
                folder = template_pattern.replace('/*', '')
                src_dir = os.path.join(current_app.root_path, 'templates', folder)
                if os.path.exists(src_dir):
                    dst_dir = os.path.join(output_dir, 'templates', folder)
                    os.makedirs(dst_dir, exist_ok=True)
                    for file in os.listdir(src_dir):
                        if file.endswith('.html'):
                            shutil.copy2(
                                os.path.join(src_dir, file),
                                os.path.join(dst_dir, file)
                            )
                            files_copied += 1
            else:
                src = os.path.join(current_app.root_path, 'templates', template_pattern)
                if os.path.exists(src):
                    dst_dir = os.path.join(output_dir, 'templates')
                    os.makedirs(dst_dir, exist_ok=True)
                    shutil.copy2(src, os.path.join(dst_dir, os.path.basename(template_pattern)))
                    files_copied += 1
        
        for static_file in files.get('static', []):
            src = os.path.join(current_app.root_path, 'static', static_file)
            if os.path.exists(src):
                dst_dir = os.path.join(output_dir, 'static', os.path.dirname(static_file))
                os.makedirs(dst_dir, exist_ok=True)
                shutil.copy2(src, os.path.join(dst_dir, os.path.basename(static_file)))
                files_copied += 1
    
    _create_custom_models_file(output_dir, modules_to_clone, available_modules)
    _create_custom_app_file(output_dir, modules_to_clone)
    _create_requirements_file(output_dir)
    _create_readme_file(output_dir, clone_name, modules_to_clone, available_modules)
    
    files_copied += 4
    
    return {
        'output_path': output_dir,
        'files_count': files_copied,
        'modules': list(modules_to_clone)
    }


def _create_custom_models_file(output_dir, selected_modules, available_modules):
    """إنشاء ملف models.py مخصص"""
    
    models_content = """# models.py - Custom System Models
# Generated by System Cloner

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from decimal import Decimal

db = SQLAlchemy()

class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AuditMixin:
    created_by_id = Column(Integer, ForeignKey('users.id'))
    updated_by_id = Column(Integer, ForeignKey('users.id'))

"""
    
    models_to_include = set()
    for module_key in selected_modules:
        module = available_modules.get(module_key)
        if module and 'files' in module:
            models_to_include.update(module['files'].get('models', []))
    
    models_content += f"\n# Selected Models: {', '.join(models_to_include)}\n"
    models_content += "# Note: Extract actual model definitions from main models.py\n\n"
    
    with open(os.path.join(output_dir, 'models.py'), 'w', encoding='utf-8') as f:
        f.write(models_content)


def _create_custom_app_file(output_dir, selected_modules):
    """إنشاء ملف app.py مخصص"""
    
    app_content = f"""# app.py - Custom System
# Generated by System Cloner
# Modules: {', '.join(selected_modules)}

from flask import Flask
import os
from flask_login import LoginManager
from extensions import db, migrate, csrf
from models import User

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        os.environ.get('DATABASE_URL')
        or os.environ.get('SQLALCHEMY_DATABASE_URI')
        or 'sqlite:///app.db'
    )
    
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))
    
"""
    
    for module in selected_modules:
        if module != 'core':
            app_content += f"    from routes.{module} import {module}_bp\n"
            app_content += f"    app.register_blueprint({module}_bp)\n"
    
    app_content += """
    return app

if __name__ == '__main__':
    app = create_app()
    debug = str(os.environ.get('FLASK_DEBUG', '') or '').strip().lower() in {'1', 'true', 'yes', 'y', 'on'}
    app.run(debug=debug)
"""
    
    with open(os.path.join(output_dir, 'app.py'), 'w', encoding='utf-8') as f:
        f.write(app_content)


def _create_requirements_file(output_dir):
    """إنشاء requirements.txt"""
    
    requirements = """Flask==3.0.0
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-Migrate==4.0.5
Flask-WTF==1.2.1
WTForms==3.1.1
"""
    
    with open(os.path.join(output_dir, 'requirements.txt'), 'w', encoding='utf-8') as f:
        f.write(requirements)


def _create_readme_file(output_dir, clone_name, selected_modules, available_modules):
    """إنشاء README.md"""
    
    readme = f"""# {clone_name}

نظام مخصص تم إنشاؤه بواسطة System Cloner

## الوحدات المضمنة:

"""
    
    for module_key in selected_modules:
        module = available_modules.get(module_key)
        if module:
            readme += f"- **{module['name']}**: {module['description']}\n"
    
    readme += """

## التثبيت:

```bash
pip install -r requirements.txt
flask db upgrade
python app.py
```

## الوصول:

```
http://localhost:5000
```

---

تم الإنشاء: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with open(os.path.join(output_dir, 'README.md'), 'w', encoding='utf-8') as f:
        f.write(readme)


@advanced_bp.route('/download-mobile-app/<app_name>')
@permission_required(SystemPermissions.MANAGE_MOBILE_APP)
def download_mobile_app(app_name):
    """تحميل تطبيق موبايل"""
    try:
        zip_path = os.path.join(current_app.root_path, 'instance', 'mobile_apps', f'{secure_filename(app_name)}.zip')
        
        if os.path.exists(zip_path):
            return send_file(zip_path, as_attachment=True, download_name=f'{app_name}.zip')
        else:
            flash('❌ التطبيق غير موجود', 'danger')
            return redirect(url_for('advanced.mobile_app_generator'))
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('advanced.mobile_app_generator'))


@advanced_bp.route('/mobile-app-generator', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_MOBILE_APP)
def mobile_app_generator():
    """مولد تطبيقات الموبايل - تحويل النظام لتطبيق Android/iOS"""
    
    if request.method == 'POST':
        app_name = request.form.get('app_name', 'GarageApp')
        app_platform = request.form.get('platform', 'both')
        selected_modules = request.form.getlist('modules')
        app_icon = request.files.get('app_icon')
        package_name = request.form.get('package_name', 'com.azad.garage')
        base_url = (request.form.get('base_url') or '').strip()
        
        try:
            result = _generate_mobile_app(
                app_name=app_name,
                platform=app_platform,
                modules=selected_modules,
                package_name=package_name,
                icon=app_icon,
                base_url=base_url
            )
            
            flash(f'✅ تم إنشاء تطبيق: {result.get("display_name") or app_name}', 'success')
            flash(f'📱 المنصة: {result["platform"]}', 'info')
            flash(f'📦 الحجم: {result["size"]}', 'info')
            flash(f'📍 الموقع: {result["output_path"]}', 'info')
            
            return redirect(url_for('advanced.mobile_app_generator', download=result.get("download_name") or app_name))
            
        except Exception as e:
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
            return redirect(url_for('advanced.mobile_app_generator'))
    
    available_modules = _get_mobile_modules()
    
                            
    apps_dir = os.path.join(current_app.root_path, 'instance', 'mobile_apps')
    mobile_apps = []
    if os.path.exists(apps_dir):
        for filename in os.listdir(apps_dir):
            if filename.endswith('.zip'):
                filepath = os.path.join(apps_dir, filename)
                size = os.path.getsize(filepath) / (1024 * 1024)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                mobile_apps.append({
                    'name': filename.replace('.zip', ''),
                    'size': f'{size:.2f} MB',
                    'date': mtime.strftime('%Y-%m-%d %H:%M')
                })
    
    download_ready = request.args.get('download')
    base_url_suggestion = (request.host_url or '').rstrip('/')
    
    return render_template('advanced/mobile_app_generator.html', 
                         modules=available_modules,
                         mobile_apps=mobile_apps,
                         download_ready=download_ready,
                         base_url_suggestion=base_url_suggestion)


def _get_mobile_modules():
    """الوحدات المتاحة لتطبيق الموبايل - جميع وحدات النظام"""
    return {
        'auth': {'name': 'تسجيل الدخول', 'icon': 'user-lock', 'required': True, 'category': 'core'},
        'dashboard': {'name': 'الداشبورد', 'icon': 'tachometer-alt', 'required': True, 'category': 'core'},
        'profile': {'name': 'الملف الشخصي', 'icon': 'user-circle', 'required': True, 'category': 'core'},
        
        'customers': {'name': 'إدارة العملاء', 'icon': 'users', 'required': False, 'category': 'business'},
        'customer_statements': {'name': 'كشوف حساب العملاء', 'icon': 'file-invoice', 'required': False, 'category': 'business'},
        
        'service': {'name': 'طلبات الصيانة', 'icon': 'wrench', 'required': False, 'category': 'business'},
        'service_create': {'name': 'إنشاء طلب صيانة', 'icon': 'plus-circle', 'required': False, 'category': 'business'},
        'service_tracking': {'name': 'تتبع الصيانة', 'icon': 'tasks', 'required': False, 'category': 'business'},
        
        'sales': {'name': 'المبيعات', 'icon': 'shopping-cart', 'required': False, 'category': 'business'},
        'sales_create': {'name': 'إنشاء فاتورة مبيعات', 'icon': 'file-invoice-dollar', 'required': False, 'category': 'business'},
        'sales_history': {'name': 'سجل المبيعات', 'icon': 'history', 'required': False, 'category': 'business'},
        
        'warehouses': {'name': 'المستودعات', 'icon': 'warehouse', 'required': False, 'category': 'inventory'},
        'parts': {'name': 'قطع الغيار', 'icon': 'cogs', 'required': False, 'category': 'inventory'},
        'stock_levels': {'name': 'مستويات المخزون', 'icon': 'boxes', 'required': False, 'category': 'inventory'},
        'preorders': {'name': 'الحجوزات', 'icon': 'bookmark', 'required': False, 'category': 'inventory'},
        
        'payments': {'name': 'الدفعات', 'icon': 'money-bill-wave', 'required': False, 'category': 'finance'},
        'payment_create': {'name': 'تسجيل دفعة', 'icon': 'cash-register', 'required': False, 'category': 'finance'},
        'checks': {'name': 'الشيكات', 'icon': 'money-check', 'required': False, 'category': 'finance'},
        'check_tracking': {'name': 'تتبع الشيكات', 'icon': 'check-circle', 'required': False, 'category': 'finance'},
        
        'expenses': {'name': 'النفقات', 'icon': 'receipt', 'required': False, 'category': 'finance'},
        'expense_create': {'name': 'تسجيل نفقة', 'icon': 'file-invoice', 'required': False, 'category': 'finance'},
        
        'vendors': {'name': 'الموردين', 'icon': 'truck', 'required': False, 'category': 'partners'},
        'partners': {'name': 'الشركاء', 'icon': 'handshake', 'required': False, 'category': 'partners'},
        'settlements': {'name': 'التسويات', 'icon': 'balance-scale', 'required': False, 'category': 'partners'},
        
        'shipments': {'name': 'الشحنات', 'icon': 'ship', 'required': False, 'category': 'logistics'},
        'shipment_tracking': {'name': 'تتبع الشحنات', 'icon': 'map-marked-alt', 'required': False, 'category': 'logistics'},
        
        'ledger': {'name': 'دفتر الأستاذ', 'icon': 'book', 'required': False, 'category': 'accounting'},
        'accounts': {'name': 'الحسابات', 'icon': 'list-alt', 'required': False, 'category': 'accounting'},
        'gl_entries': {'name': 'القيود المحاسبية', 'icon': 'edit', 'required': False, 'category': 'accounting'},
        
        'currencies': {'name': 'العملات', 'icon': 'dollar-sign', 'required': False, 'category': 'settings'},
        'exchange_rates': {'name': 'أسعار الصرف', 'icon': 'exchange-alt', 'required': False, 'category': 'settings'},
        
        'reports': {'name': 'التقارير', 'icon': 'chart-bar', 'required': False, 'category': 'analytics'},
        'financial_reports': {'name': 'التقارير المالية', 'icon': 'chart-line', 'required': False, 'category': 'analytics'},
        'sales_reports': {'name': 'تقارير المبيعات', 'icon': 'chart-pie', 'required': False, 'category': 'analytics'},
        'inventory_reports': {'name': 'تقارير المخزون', 'icon': 'chart-area', 'required': False, 'category': 'analytics'},
        
        'shop': {'name': 'المتجر الإلكتروني', 'icon': 'store', 'required': False, 'category': 'ecommerce'},
        'cart': {'name': 'سلة التسوق', 'icon': 'shopping-basket', 'required': False, 'category': 'ecommerce'},
        'orders': {'name': 'الطلبات', 'icon': 'clipboard-list', 'required': False, 'category': 'ecommerce'},
        
        'notifications': {'name': 'الإشعارات', 'icon': 'bell', 'required': False, 'category': 'features'},
        'scanner': {'name': 'قارئ الباركود', 'icon': 'barcode', 'required': False, 'category': 'features'},
        'camera': {'name': 'الكاميرا', 'icon': 'camera', 'required': False, 'category': 'features'},
        'gps': {'name': 'تتبع الموقع', 'icon': 'map-marker-alt', 'required': False, 'category': 'features'},
        'offline_mode': {'name': 'وضع عدم الاتصال', 'icon': 'wifi-slash', 'required': False, 'category': 'features'},
        'sync': {'name': 'المزامنة', 'icon': 'sync', 'required': False, 'category': 'features'},
        
        'settings': {'name': 'الإعدادات', 'icon': 'cog', 'required': False, 'category': 'system'},
        'help': {'name': 'المساعدة', 'icon': 'question-circle', 'required': False, 'category': 'system'},
        'about': {'name': 'حول التطبيق', 'icon': 'info-circle', 'required': False, 'category': 'system'},
    }


def _generate_mobile_app(app_name, platform, modules, package_name, icon=None, base_url=""):
    """إنشاء تطبيق موبايل"""

    import re
    from urllib.parse import urlparse

    safe_app_dir = secure_filename(app_name) or "GarageApp"
    app_name_clean = (app_name or "GarageApp").strip()[:60] or "GarageApp"

    package_name_clean = (package_name or "").strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+", package_name_clean):
        raise ValueError("اسم الحزمة غير صحيح. مثال: com.example.app")

    base_url_clean = (base_url or "").strip()
    if not base_url_clean:
        base_url_clean = (request.host_url or "").rstrip("/")
    if not base_url_clean:
        raise ValueError("رابط النظام مطلوب")

    parsed = urlparse(base_url_clean)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("رابط النظام غير صحيح. مثال: https://example.com")
    base_url_clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}".rstrip("/")

    if platform in ["ios", "both"]:
        raise ValueError("مولد iOS غير جاهز حالياً لتجنب توليد مشروع غير قابل للبناء")

    output_dir = os.path.join(current_app.root_path, "instance", "mobile_apps", safe_app_dir)
    os.makedirs(output_dir, exist_ok=True)

    _create_android_project(
        output_dir=output_dir,
        app_name=app_name_clean,
        package_name=package_name_clean,
        modules=modules,
        icon=icon,
        base_url=base_url_clean,
    )
    _create_mobile_readme(output_dir, app_name_clean, "android", modules, base_url_clean)
    
    import zipfile
    zip_path = os.path.join(current_app.root_path, "instance", "mobile_apps", f"{safe_app_dir}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(output_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, output_dir)
                zipf.write(file_path, arcname)
    
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    
    return {
        'output_path': output_dir,
        'zip_path': zip_path,
        'platform': "android",
        'size': f'{size_mb:.2f} MB',
        'download_name': safe_app_dir,
        'display_name': app_name_clean
    }


def _create_flutter_project(output_dir, app_name, package_name, modules):
    """إنشاء مشروع Flutter"""
    
    flutter_dir = os.path.join(output_dir, 'flutter_app')
    os.makedirs(flutter_dir, exist_ok=True)
    
    pubspec = f"""name: {app_name.lower().replace(' ', '_')}
description: تطبيق {app_name}
version: 1.0.0+1

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  http: ^1.1.0
  provider: ^6.0.5
  shared_preferences: ^2.2.2
  flutter_secure_storage: ^9.0.0
  barcode_scan2: ^4.2.3
  image_picker: ^1.0.4
  geolocator: ^10.1.0
  url_launcher: ^6.2.1
  intl: ^0.18.1

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0

flutter:
  uses-material-design: true
"""
    
    with open(os.path.join(flutter_dir, 'pubspec.yaml'), 'w', encoding='utf-8') as f:
        f.write(pubspec)
    
    main_dart = f"""import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

void main() {{
  runApp(MyApp());
}}

class MyApp extends StatelessWidget {{
  @override
  Widget build(BuildContext context) {{
    return MaterialApp(
      title: '{app_name}',
      theme: ThemeData(
        primarySwatch: Colors.blue,
        fontFamily: 'Cairo',
      ),
      home: LoginScreen(),
      routes: {{
        '/dashboard': (context) => DashboardScreen(),
        '/customers': (context) => CustomersScreen(),
        '/sales': (context) => SalesScreen(),
      }},
    );
  }}
}}

class LoginScreen extends StatelessWidget {{
  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      body: Center(
        child: Text('Login Screen - {app_name}'),
      ),
    );
  }}
}}

class DashboardScreen extends StatelessWidget {{
  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      appBar: AppBar(title: Text('Dashboard')),
      body: Center(child: Text('Dashboard')),
    );
  }}
}}

class CustomersScreen extends StatelessWidget {{
  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      appBar: AppBar(title: Text('العملاء')),
      body: Center(child: Text('Customers List')),
    );
  }}
}}

class SalesScreen extends StatelessWidget {{
  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      appBar: AppBar(title: Text('المبيعات')),
      body: Center(child: Text('Sales List')),
    );
  }}
}}
"""
    
    lib_dir = os.path.join(flutter_dir, 'lib')
    os.makedirs(lib_dir, exist_ok=True)
    with open(os.path.join(lib_dir, 'main.dart'), 'w', encoding='utf-8') as f:
        f.write(main_dart)


def _create_android_project(output_dir, app_name, package_name, modules, icon, base_url):
    """إنشاء مشروع Android"""

    import re

    project_dir = os.path.join(output_dir, "android")
    app_dir = os.path.join(project_dir, "app")
    src_main = os.path.join(app_dir, "src", "main")
    java_dir = os.path.join(src_main, "java")
    res_dir = os.path.join(src_main, "res")

    for p in [project_dir, app_dir, src_main, java_dir, res_dir]:
        os.makedirs(p, exist_ok=True)

    safe_project_name = re.sub(r"[^A-Za-z0-9_]", "_", app_name.strip()) or "GarageApp"

    settings_gradle = f"""pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}

dependencyResolutionManagement {{
    repositories {{
        google()
        mavenCentral()
    }}
}}

rootProject.name = "{safe_project_name}"
include(":app")
"""
    with open(os.path.join(project_dir, "settings.gradle.kts"), "w", encoding="utf-8") as f:
        f.write(settings_gradle)

    root_gradle = """buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("com.android.tools.build:gradle:8.2.2")
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:1.9.22")
    }
}

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}
"""
    with open(os.path.join(project_dir, "build.gradle.kts"), "w", encoding="utf-8") as f:
        f.write(root_gradle)

    gradle_props = """org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
android.enableJetifier=true
kotlin.code.style=official
"""
    with open(os.path.join(project_dir, "gradle.properties"), "w", encoding="utf-8") as f:
        f.write(gradle_props)

    app_gradle = f"""plugins {{
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}}

android {{
    namespace = "{package_name}"
    compileSdk = 34

    defaultConfig {{
        applicationId = "{package_name}"
        minSdk = 21
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }}

    buildTypes {{
        release {{
            isMinifyEnabled = false
        }}
    }}

    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}

    kotlinOptions {{
        jvmTarget = "17"
    }}
}}

dependencies {{
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
}}
"""
    with open(os.path.join(app_dir, "build.gradle.kts"), "w", encoding="utf-8") as f:
        f.write(app_gradle)

    package_path = package_name.replace(".", os.sep)
    main_pkg_dir = os.path.join(java_dir, package_path)
    os.makedirs(main_pkg_dir, exist_ok=True)

    os.makedirs(os.path.join(res_dir, "layout"), exist_ok=True)
    os.makedirs(os.path.join(res_dir, "values"), exist_ok=True)
    os.makedirs(os.path.join(res_dir, "xml"), exist_ok=True)

    network_security = """<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
        </trust-anchors>
    </base-config>
</network-security-config>
"""
    with open(os.path.join(res_dir, "xml", "network_security_config.xml"), "w", encoding="utf-8") as f:
        f.write(network_security)

    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package_name}">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />

    <application
        android:label="@string/app_name"
        android:icon="@mipmap/ic_launcher"
        android:roundIcon="@mipmap/ic_launcher"
        android:theme="@style/Theme.GarageApp"
        android:usesCleartextTraffic="true"
        android:networkSecurityConfig="@xml/network_security_config">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:launchMode="singleTask"
            android:screenOrientation="portrait"
            android:theme="@style/Theme.GarageApp">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>

</manifest>
"""
    with open(os.path.join(src_main, "AndroidManifest.xml"), "w", encoding="utf-8") as f:
        f.write(manifest)

    strings_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
    <string name="app_base_url">{base_url}</string>
</resources>
"""
    with open(os.path.join(res_dir, "values", "strings.xml"), "w", encoding="utf-8") as f:
        f.write(strings_xml)

    themes_xml = """<?xml version="1.0" encoding="utf-8"?>
<resources xmlns:tools="http://schemas.android.com/tools">
    <style name="Theme.GarageApp" parent="Theme.MaterialComponents.DayNight.NoActionBar">
        <item name="android:statusBarColor">@android:color/transparent</item>
        <item name="android:navigationBarColor">@android:color/black</item>
        <item name="android:windowLightStatusBar" tools:targetApi="m">false</item>
    </style>
</resources>
"""
    with open(os.path.join(res_dir, "values", "themes.xml"), "w", encoding="utf-8") as f:
        f.write(themes_xml)

    colors_xml = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">#667EEA</color>
</resources>
"""
    with open(os.path.join(res_dir, "values", "colors.xml"), "w", encoding="utf-8") as f:
        f.write(colors_xml)

    os.makedirs(os.path.join(res_dir, "drawable"), exist_ok=True)
    ic_foreground = """<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <path
        android:fillColor="#FFFFFF"
        android:pathData="M54,18c-19.882,0 -36,16.118 -36,36s16.118,36 36,36 36,-16.118 36,-36S73.882,18 54,18z" />
</vector>
"""
    with open(os.path.join(res_dir, "drawable", "ic_launcher_foreground.xml"), "w", encoding="utf-8") as f:
        f.write(ic_foreground)

    os.makedirs(os.path.join(res_dir, "mipmap-anydpi-v26"), exist_ok=True)
    ic_launcher_xml = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
</adaptive-icon>
"""
    with open(os.path.join(res_dir, "mipmap-anydpi-v26", "ic_launcher.xml"), "w", encoding="utf-8") as f:
        f.write(ic_launcher_xml)
    with open(os.path.join(res_dir, "mipmap-anydpi-v26", "ic_launcher_round.xml"), "w", encoding="utf-8") as f:
        f.write(ic_launcher_xml)

    activity_main = """<?xml version="1.0" encoding="utf-8"?>
<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent">

    <WebView
        android:id="@+id/webview"
        android:layout_width="match_parent"
        android:layout_height="match_parent" />

</FrameLayout>
"""
    with open(os.path.join(res_dir, "layout", "activity_main.xml"), "w", encoding="utf-8") as f:
        f.write(activity_main)

    main_activity = f"""package {package_name}

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.webkit.URLUtil
import android.webkit.GeolocationPermissions
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {{
    private lateinit var webView: WebView
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private val fileChooserRequestCode = 1001

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webview)
        val s = webView.settings
        s.javaScriptEnabled = true
        s.domStorageEnabled = true
        s.databaseEnabled = true
        s.cacheMode = WebSettings.LOAD_DEFAULT
        s.javaScriptCanOpenWindowsAutomatically = false
        s.setSupportMultipleWindows(false)
        s.mediaPlaybackRequiresUserGesture = false
        s.allowFileAccess = false
        s.allowContentAccess = false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {{
            s.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
        }}
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            s.safeBrowsingEnabled = true
        }}

        webView.webViewClient = object : WebViewClient() {{
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {{
                val u = request.url
                val scheme = u.scheme ?: ""
                if (scheme == "http" || scheme == "https") {{
                    return false
                }}
                return try {{
                    startActivity(Intent(Intent.ACTION_VIEW, u))
                    true
                }} catch (e: Exception) {{
                    false
                }}
            }}
        }}

        webView.webChromeClient = object : WebChromeClient() {{
            override fun onPermissionRequest(request: PermissionRequest) {{
                runOnUiThread {{
                    request.grant(request.resources)
                }}
            }}

            override fun onGeolocationPermissionsShowPrompt(
                origin: String,
                callback: GeolocationPermissions.Callback
            ) {{
                callback.invoke(origin, true, false)
            }}

            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                fileChooserParams: FileChooserParams
            ): Boolean {{
                this@MainActivity.filePathCallback?.onReceiveValue(null)
                this@MainActivity.filePathCallback = filePathCallback
                return try {{
                    startActivityForResult(fileChooserParams.createIntent(), fileChooserRequestCode)
                    true
                }} catch (e: Exception) {{
                    this@MainActivity.filePathCallback = null
                    false
                }}
            }}
        }}

        val url = getString(R.string.app_base_url)
        webView.loadUrl(url)
    }}

    @Deprecated("Deprecated in Android")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {{
        if (requestCode == fileChooserRequestCode) {{
            val result = WebChromeClient.FileChooserParams.parseResult(resultCode, data)
            filePathCallback?.onReceiveValue(result)
            filePathCallback = null
            return
        }}
        super.onActivityResult(requestCode, resultCode, data)
    }}

    override fun onBackPressed() {{
        if (webView.canGoBack()) {{
            webView.goBack()
        }} else {{
            super.onBackPressed()
        }}
    }}
}}
"""
    with open(os.path.join(main_pkg_dir, "MainActivity.kt"), "w", encoding="utf-8") as f:
        f.write(main_activity)

    if icon and getattr(icon, "filename", ""):
        try:
            icon.seek(0)
            icon_bytes = icon.read()
            if icon_bytes:
                for d in ["mipmap-mdpi", "mipmap-hdpi", "mipmap-xhdpi", "mipmap-xxhdpi", "mipmap-xxxhdpi"]:
                    os.makedirs(os.path.join(res_dir, d), exist_ok=True)
                    with open(os.path.join(res_dir, d, "ic_launcher.png"), "wb") as f:
                        f.write(icon_bytes)
        except Exception:
            current_app.logger.debug('file operation failed in advanced_control.py', exc_info=True)


def _create_ios_project(output_dir, app_name, package_name, modules, icon):
    """إنشاء مشروع iOS"""
    
    raise ValueError("مولد iOS غير جاهز حالياً لتجنب توليد مشروع غير قابل للبناء")


def _create_react_native_config(output_dir, app_name, package_name, modules):
    """إنشاء React Native config"""
    
    rn_dir = os.path.join(output_dir, 'react_native')
    os.makedirs(rn_dir, exist_ok=True)
    
    package_json = f"""{{
  "name": "{app_name.lower().replace(' ', '-')}",
  "version": "1.0.0",
  "private": true,
  "scripts": {{
    "android": "react-native run-android",
    "ios": "react-native run-ios",
    "start": "react-native start"
  }},
  "dependencies": {{
    "react": "18.2.0",
    "react-native": "0.73.0",
    "react-navigation": "^4.4.4",
    "axios": "^1.6.0",
    "@react-native-async-storage/async-storage": "^1.19.0",
    "react-native-camera": "^4.2.1",
    "react-native-barcode-scanner": "^1.0.0"
  }}
}}
"""
    
    with open(os.path.join(rn_dir, 'package.json'), 'w', encoding='utf-8') as f:
        f.write(package_json)
    
    app_js = f"""import React from 'react';
import {{ NavigationContainer }} from '@react-navigation/native';
import {{ createStackNavigator }} from '@react-navigation/stack';
import LoginScreen from './screens/LoginScreen';
import DashboardScreen from './screens/DashboardScreen';

const Stack = createStackNavigator();

export default function App() {{
  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Login">
        <Stack.Screen name="Login" component={{LoginScreen}} options={{{{ headerShown: false }}}} />
        <Stack.Screen name="Dashboard" component={{DashboardScreen}} options={{{{ title: '{app_name}' }}}} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}}
"""
    
    with open(os.path.join(rn_dir, 'App.js'), 'w', encoding='utf-8') as f:
        f.write(app_js)


def _create_mobile_readme(output_dir, app_name, platform, modules, base_url):
    """إنشاء README للتطبيق"""
    
    readme = f"""# {app_name} - Mobile App

تطبيق موبايل تم إنشاؤه بواسطة Mobile App Generator

## المنصات:
- ✅ Android (WebView Wrapper)
- ❌ iOS (غير متاح حالياً)

## التقنيات المستخدمة:
- **Android Native**: Kotlin + WebView

## الوحدات المضمنة:
{len(modules)} وحدة

## البناء:

### Android Native:
```bash
cd android
```

## الاتصال بالسيرفر:

تأكد من تحديث رابط النظام داخل:
- Android: `app/src/main/res/values/strings.xml`

```
app_base_url = "{base_url}"
```

---

تم الإنشاء: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    
    with open(os.path.join(output_dir, 'README_MOBILE.md'), 'w', encoding='utf-8') as f:
        f.write(readme)


def _detect_current_db_type():
    """كشف نوع قاعدة البيانات الحالية"""
    try:
        uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if uri.startswith(('postgresql', 'postgres')):
            return 'PostgreSQL'
        dialect = getattr(db.engine, "dialect", None)
        dialect_name = str(getattr(dialect, "name", "") or "").strip()
        return dialect_name.title() if dialect_name else 'Unknown'
    except Exception:
        return 'Unknown'


def _convert_database(target_db, connection_string):
    """تحويل قاعدة البيانات من نوع لآخر - محسّن وقوي"""
    raise ValueError("db_conversion_disabled_postgresql_only")


def _get_all_tenants():
    """جلب جميع Tenants مع تفاصيلهم - محسّن مع cache و batch loading"""
    cache_key = "all_tenants_list"
    cached_list = cache.get(cache_key)
    if cached_list is not None:
        return cached_list

    registry_rows = TenantRegistry.query.all()
    registry_by_slug = {row.slug: row for row in registry_rows if row.slug}
    
    tenant_db_settings = SystemSettings.query.filter(
        SystemSettings.key.like('tenant_%_db')
    ).all()
    
    tenant_names = [t.key.replace('tenant_', '').replace('_db', '') for t in tenant_db_settings]
    tenant_names = sorted(set(tenant_names) | set(registry_by_slug.keys()))

    if not tenant_names:
        return []

    db_map = {t.key.replace('tenant_', '').replace('_db', ''): t.value for t in tenant_db_settings}
    
    all_settings = SystemSettings.query.filter(
        or_(
            *[SystemSettings.key.like(f'tenant_{name}_%') for name in tenant_names]
        )
    ).all()
    
    settings_dict = {}
    for setting in all_settings:
        for name in tenant_names:
            if setting.key.startswith(f'tenant_{name}_'):
                if name not in settings_dict:
                    settings_dict[name] = {}
                key_suffix = setting.key.replace(f'tenant_{name}_', '')
                settings_dict[name][key_suffix] = setting.value
                break
    
    tenant_list = []
    for name in tenant_names:
        registry = registry_by_slug.get(name)
        tenant_settings = settings_dict.get(name, {})
        
        modules = []
        if tenant_settings.get('modules'):
            try:
                modules = json.loads(tenant_settings['modules'])
            except Exception:
                modules = []

        schema_name = (getattr(registry, 'schema_name', None) or _make_tenant_schema_name(name) or '')
        domain = (getattr(registry, 'domain', None) or tenant_settings.get('domain', '') or '')
        active = getattr(registry, 'is_active', None)
        if active is None:
            active = tenant_settings.get('active', 'False') == 'True'
        
        tenant_list.append({
            'name': name,
            'slug': name,
            'schema_name': schema_name,
            'db': db_map.get(name, ''),
            'active': bool(active),
            'domain': domain,
            'logo': tenant_settings.get('logo', ''),
            'company_name': tenant_settings.get('company_name', ''),
            'system_name': tenant_settings.get('system_name', ''),
            'favicon': tenant_settings.get('favicon', ''),
            'max_users': tenant_settings.get('max_users', '10'),
            'modules': modules,
            'created_at': tenant_settings.get('created_at', '')
        })
    
    cache.set(cache_key, tenant_list, timeout=300)
    return tenant_list


def _prepare_tenants(tenants):
    prepared = []
    for tenant in tenants:
        raw_max = tenant.get('max_users', '0') or '0'
        try:
            max_users_num = int(raw_max)
        except Exception:
            max_users_num = 0
        issues = []
        if not tenant.get('domain'):
            issues.append('missing_domain')
        if not tenant.get('logo'):
            issues.append('missing_logo')
        prepared.append({
            **tenant,
            'max_users_num': max_users_num,
            'issues': issues,
        })
    return prepared


def _build_tenant_filters(args):
    return {
        'search': (args.get('q') or '').strip(),
        'status': args.get('status', 'all'),
        'module': args.get('module', 'all'),
    }


def _filter_tenants(tenants, filters):
    search = filters['search'].lower()
    status = filters['status']
    module = filters['module']
    filtered = []
    for tenant in tenants:
        name = tenant['name'].lower()
        domain = (tenant.get('domain') or '').lower()
        db_value = (tenant.get('db') or '').lower()
        if search and search not in name and search not in domain and search not in db_value:
            continue
        if status == 'active' and not tenant['active']:
            continue
        if status == 'inactive' and tenant['active']:
            continue
        if module != 'all':
            modules = tenant.get('modules') or []
            if module not in modules:
                continue
        filtered.append(tenant)
    return filtered


def _build_tenant_stats(tenants):
    total = len(tenants)
    active = sum(1 for tenant in tenants if tenant['active'])
    inactive = total - active
    total_limit = sum(tenant.get('max_users_num', 0) for tenant in tenants)
    missing_domain = sum(1 for tenant in tenants if 'missing_domain' in tenant.get('issues', []))
    missing_logo = sum(1 for tenant in tenants if 'missing_logo' in tenant.get('issues', []))
    return {
        'total_tenants': total,
        'active_tenants': active,
        'inactive_tenants': inactive,
        'total_users_limit': total_limit,
        'missing_domain': missing_domain,
        'missing_logo': missing_logo,
    }


def _calculate_module_usage(tenants, modules):
    counts = {}
    for tenant in tenants:
        for mod_key in tenant.get('modules') or []:
            counts[mod_key] = counts.get(mod_key, 0) + 1
    result = []
    for module in modules:
        result.append({
            'key': module['key'],
            'name': module['name'],
            'icon': module['icon'],
            'count': counts.get(module['key'], 0),
        })
    result.sort(key=lambda item: item['count'], reverse=True)
    return result


def _update_tenant_setting(key, value):
    """تحديث أو إنشاء إعداد Tenant"""
    setting = SystemSettings.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        db.session.add(SystemSettings(key=key, value=value))


def _get_available_modules_list():
    """قائمة الوحدات المتاحة"""
    return [
        {'key': 'customers', 'name': 'إدارة العملاء', 'icon': 'users'},
        {'key': 'service', 'name': 'الصيانة', 'icon': 'wrench'},
        {'key': 'sales', 'name': 'المبيعات', 'icon': 'shopping-cart'},
        {'key': 'warehouses', 'name': 'المستودعات', 'icon': 'warehouse'},
        {'key': 'vendors', 'name': 'الموردين', 'icon': 'truck'},
        {'key': 'partners', 'name': 'الشركاء', 'icon': 'handshake'},
        {'key': 'shipments', 'name': 'الشحنات', 'icon': 'ship'},
        {'key': 'payments', 'name': 'الدفعات', 'icon': 'money-bill-wave'},
        {'key': 'checks', 'name': 'الشيكات', 'icon': 'money-check'},
        {'key': 'expenses', 'name': 'النفقات', 'icon': 'receipt'},
        {'key': 'ledger', 'name': 'دفتر الأستاذ', 'icon': 'book'},
        {'key': 'currencies', 'name': 'العملات', 'icon': 'dollar-sign'},
        {'key': 'reports', 'name': 'التقارير', 'icon': 'chart-bar'},
        {'key': 'shop', 'name': 'المتجر', 'icon': 'store'},
        {'key': 'security', 'name': 'الأمان', 'icon': 'shield-alt'},
    ]


def _create_tenant_database(db_path):
    """إنشاء قاعدة بيانات جديدة للـ Tenant"""
    raise ValueError("tenant_db_creation_disabled_postgresql_only")


@advanced_bp.route('/financial-control', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def financial_control():
    from models import SystemSettings, Budget, FixedAsset, FixedAssetCategory
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'save_budget_settings':
            settings_data = {
                'enable_budget_module': request.form.get('enable_budget_module') == 'on',
                'fiscal_year_start_month': _to_float(request.form.get('fiscal_year_start_month', 1), 1),
                'budget_level': request.form.get('budget_level', 'ACCOUNT_BRANCH'),
                'commitment_mode': request.form.get('commitment_mode', 'ALL'),
                'enable_budget_alerts': request.form.get('enable_budget_alerts') == 'on',
                'budget_threshold_warning': _to_float(request.form.get('budget_threshold_warning', 80), 80),
                'budget_threshold_critical': _to_float(request.form.get('budget_threshold_critical', 95), 95),
                'enable_budget_blocking': request.form.get('enable_budget_blocking') == 'on',
            }
            
            for key, value in settings_data.items():
                setting = SystemSettings.query.filter_by(key=key).first()
                if setting:
                    setting.value = str(value)
                    setting.updated_at = datetime.now(timezone.utc)
                else:
                    dtype = 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'string'
                    setting = SystemSettings(key=key, value=str(value), data_type=dtype, is_public=False)
                    db.session.add(setting)
            
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                return jsonify({'success': False, 'error': 'حدث خطأ داخلي'}), 500
            flash('تم حفظ إعدادات الميزانية بنجاح', 'success')
            return redirect(url_for('advanced.financial_control'))
        
        elif action == 'save_asset_settings':
            settings_data = {
                'enable_fixed_assets': request.form.get('enable_fixed_assets') == 'on',
                'enable_auto_depreciation': request.form.get('enable_auto_depreciation') == 'on',
                'depreciation_frequency': request.form.get('depreciation_frequency', 'YEARLY'),
                'depreciation_day_of_month': _to_float(request.form.get('depreciation_day_of_month', 1), 1),
                'auto_create_asset_from_expense': request.form.get('auto_create_asset_from_expense') == 'on',
                'asset_capitalization_threshold': _to_float(request.form.get('asset_capitalization_threshold', 1000), 1000),
            }
            
            for key, value in settings_data.items():
                setting = SystemSettings.query.filter_by(key=key).first()
                if setting:
                    setting.value = str(value)
                    setting.updated_at = datetime.now(timezone.utc)
                else:
                    dtype = 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'string'
                    setting = SystemSettings(key=key, value=str(value), data_type=dtype, is_public=False)
                    db.session.add(setting)
            
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('commit error')
                return jsonify({'success': False, 'error': 'حدث خطأ داخلي'}), 500
            flash('تم حفظ إعدادات الأصول الثابتة بنجاح', 'success')
            return redirect(url_for('advanced.financial_control'))
    
    budget_settings = {
        'enable_budget_module': SystemSettings.get_setting('enable_budget_module', False),
        'fiscal_year_start_month': int(SystemSettings.get_setting('fiscal_year_start_month', 1)),
        'budget_level': SystemSettings.get_setting('budget_level', 'ACCOUNT_BRANCH'),
        'commitment_mode': SystemSettings.get_setting('commitment_mode', 'ALL'),
        'enable_budget_alerts': SystemSettings.get_setting('enable_budget_alerts', True),
        'budget_threshold_warning': float(SystemSettings.get_setting('budget_threshold_warning', 80)),
        'budget_threshold_critical': float(SystemSettings.get_setting('budget_threshold_critical', 95)),
        'enable_budget_blocking': SystemSettings.get_setting('enable_budget_blocking', True),
    }
    
    asset_settings = {
        'enable_fixed_assets': SystemSettings.get_setting('enable_fixed_assets', False),
        'enable_auto_depreciation': SystemSettings.get_setting('enable_auto_depreciation', False),
        'depreciation_frequency': SystemSettings.get_setting('depreciation_frequency', 'YEARLY'),
        'depreciation_day_of_month': int(SystemSettings.get_setting('depreciation_day_of_month', 1)),
        'auto_create_asset_from_expense': SystemSettings.get_setting('auto_create_asset_from_expense', False),
        'asset_capitalization_threshold': float(SystemSettings.get_setting('asset_capitalization_threshold', 1000)),
    }
    
    budget_stats = {
        'total_budgets': Budget.query.count(),
        'active_budgets': Budget.query.filter_by(is_active=True).count(),
        'current_year_budgets': Budget.query.filter_by(fiscal_year=datetime.now().year).count(),
    }
    
    asset_stats = {
        'total_assets': FixedAsset.query.count(),
        'active_assets': FixedAsset.query.filter_by(status='ACTIVE').count(),
        'total_categories': FixedAssetCategory.query.count(),
    }
    
    return render_template('advanced/financial_control.html',
                         budget_settings=budget_settings,
                         asset_settings=asset_settings,
                         budget_stats=budget_stats,
                         asset_stats=asset_stats)


@advanced_bp.route("/accounting-control", methods=["GET", "POST"])
@permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def accounting_control():
    settings_bundle = _get_accounting_settings_bundle()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "save_bank_settings":
            _save_bank_settings(request.form, base=settings_bundle["bank"])
            flash("تم حفظ إعدادات البنوك", "success")
            return redirect(url_for("advanced.accounting_control"))
        
        elif action == "save_cost_center_settings":
            _save_cost_center_settings(request.form, base=settings_bundle["cost_centers"])
            flash("تم حفظ إعدادات مراكز التكلفة", "success")
            return redirect(url_for("advanced.accounting_control"))
        
        elif action == "save_project_settings":
            _save_project_settings(request.form, base=settings_bundle["projects"])
            flash("تم حفظ إعدادات المشاريع", "success")
            return redirect(url_for("advanced.accounting_control"))
        
        elif action == "save_automation_settings":
            _save_automation_settings(request.form, base=settings_bundle["automation"])
            flash("تم حفظ إعدادات الأتمتة", "success")
            return redirect(url_for("advanced.accounting_control"))
        
        elif action == "save_security_settings":
            _save_security_settings(request.form, base=settings_bundle["security"])
            flash("تم حفظ إعدادات الأمان", "success")
            return redirect(url_for("advanced.accounting_control"))
    
    stats = _calculate_accounting_overview(settings_bundle)
    
    return render_template("advanced/accounting_control.html",
                         bank_settings=settings_bundle["bank"],
                         cost_center_settings=settings_bundle["cost_centers"],
                         project_settings=settings_bundle["projects"],
                         automation_settings=settings_bundle["automation"],
                         security_settings=settings_bundle["security"],
                         stats=stats)


@advanced_bp.route("/api/advanced-accounting-stats")
@permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def api_accounting_stats():
    from models import BankTransaction
    
    stats = _calculate_accounting_overview()
    unmatched = BankTransaction.query.filter_by(matched=False).count()
    
    return jsonify({
        'success': True,
        'stats': {
            'bank_accounts': stats['total_bank_accounts'],
            'active_banks': stats['active_bank_accounts'],
            'cost_centers': stats['total_cost_centers'],
            'active_cost_centers': stats['active_cost_centers'],
            'total_budget': stats['total_budget'],
            'projects': stats['total_projects'],
            'active_projects': stats['active_projects'],
            'alerts': unmatched
        }
    })


@advanced_bp.route("/accounting-control/export-settings", methods=["GET"])
@permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def accounting_control_export_settings():
    settings_bundle = _get_accounting_settings_bundle()
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings_bundle,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    filename = f"accounting_settings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        data,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@advanced_bp.route("/accounting-control/import-settings", methods=["POST"])
@permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def accounting_control_import_settings():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"success": False, "message": "لم يتم إرسال بيانات"}), 400
    settings_payload = payload.get("settings") or payload
    if not isinstance(settings_payload, dict):
        return jsonify({"success": False, "message": "تنسيق غير صالح"}), 400
    settings_bundle = _get_accounting_settings_bundle()
    applied = {}
    if isinstance(settings_payload.get("bank"), dict):
        applied["bank"] = _save_bank_settings(settings_payload["bank"], base=settings_bundle["bank"], preserve_missing=True)
    if isinstance(settings_payload.get("cost_centers"), dict):
        applied["cost_centers"] = _save_cost_center_settings(settings_payload["cost_centers"], base=settings_bundle["cost_centers"], preserve_missing=True)
    if isinstance(settings_payload.get("projects"), dict):
        applied["projects"] = _save_project_settings(settings_payload["projects"], base=settings_bundle["projects"], preserve_missing=True)
    if isinstance(settings_payload.get("automation"), dict):
        applied["automation"] = _save_automation_settings(settings_payload["automation"], base=settings_bundle["automation"], preserve_missing=True)
    if isinstance(settings_payload.get("security"), dict):
        applied["security"] = _save_security_settings(settings_payload["security"], base=settings_bundle["security"], preserve_missing=True)
    if not applied:
        return jsonify({"success": False, "message": "لا توجد إعدادات مطبقة"}), 400
    refreshed = _get_accounting_settings_bundle()
    return jsonify({"success": True, "applied": applied, "settings": refreshed})


@advanced_bp.route("/accounting-control/system-check", methods=["GET"])
@permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def accounting_control_system_check():
    report = _run_accounting_system_check()
    return jsonify({"success": True, "report": report})


@advanced_bp.route("/accounting-control/manual-backup", methods=["POST"])
@permission_required(SystemPermissions.BACKUP_DATABASE)
def accounting_control_manual_backup():
    manager = AutomatedBackupManager(current_app._get_current_object())
    backup_path = manager.create_backup()
    if not backup_path:
        return jsonify({"success": False, "message": "تعذر إنشاء النسخة الاحتياطية"}), 400
    status = manager.get_backup_status()
    latest_backup = status.get("latest_backup")
    if latest_backup and isinstance(latest_backup.get("date"), datetime):
        status["latest_backup"]["date"] = latest_backup["date"].strftime("%Y-%m-%d %H:%M")
    size_mb = None
    if backup_path and hasattr(backup_path, "stat"):
        try:
            size_mb = backup_path.stat().st_size / (1024 * 1024)
        except OSError:
            size_mb = None
    return jsonify({
        "success": True,
        "filename": backup_path.name if hasattr(backup_path, "name") else str(backup_path),
        "size_mb": size_mb,
        "status": status
    })


@advanced_bp.route("/accounting-control/report.pdf", methods=["GET"])
@permission_required(SystemPermissions.MANAGE_ADVANCED_ACCOUNTING)
def accounting_control_report_pdf():
    settings_bundle = _get_accounting_settings_bundle()
    stats = _calculate_accounting_overview(settings_bundle)
    diagnostics = _run_accounting_system_check()
    html = render_template_string(
        ACCOUNTING_REPORT_TEMPLATE,
        settings=settings_bundle,
        stats=stats,
        diagnostics=diagnostics,
        generated_at=datetime.now(timezone.utc)
    )
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html, base_url=request.url_root).write_pdf()
        filename = f"accounting_control_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"},
        )
    except Exception as exc:
        current_app.logger.warning("accounting_control_report_pdf: WeasyPrint unavailable: %s", exc)
        flash("تعذر إنشاء PDF (مكتبة الطباعة غير متوفرة). يُعرض التقرير كصفحة HTML.", "warning")
        return Response(html, mimetype="text/html; charset=utf-8")


@advanced_bp.route('/performance-profiler', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_HEALTH)
def performance_profiler():
    """Performance Profiler - تحليل أداء النظام"""
    from sqlalchemy import text
    import time
    
    cache_key = "performance_profiler_data"
    cached_data = cache.get(cache_key)
    
    if cached_data is None:
        profiler_data = {
            'database': {},
            'queries': [],
            'cache_stats': {},
            'system': {}
        }
        
        try:
            start = time.time()
            db.session.execute(text("SELECT 1"))
            profiler_data['database']['connection_time'] = round((time.time() - start) * 1000, 2)
            
            start = time.time()
            db.session.execute(text("SELECT COUNT(*) FROM users"))
            profiler_data['database']['simple_query_time'] = round((time.time() - start) * 1000, 2)
            
            inspector = inspect(db.engine)
            tables = list(inspector.get_table_names() or [])
            profiler_data['database']['table_count'] = len(tables)
            
            slow_queries = []
            preparer = db.engine.dialect.identifier_preparer
            for table in tables[:10]:
                try:
                    start = time.time()
                    quoted = preparer.quote(table)
                    db.session.execute(text(f"SELECT COUNT(*) FROM {quoted}"))
                    elapsed = (time.time() - start) * 1000
                    if elapsed > 100:
                        slow_queries.append({
                            'table': table,
                            'time_ms': round(elapsed, 2),
                            'query': f"SELECT COUNT(*) FROM {table}"
                        })
                except Exception:
                    continue
            
            profiler_data['queries'] = sorted(slow_queries, key=lambda x: x['time_ms'], reverse=True)[:10]
            
            try:
                import psutil
                process = psutil.Process()
                profiler_data['system'] = {
                    'memory_mb': round(process.memory_info().rss / (1024 * 1024), 2),
                    'cpu_percent': process.cpu_percent(interval=0.1),
                    'threads': process.num_threads()
                }
            except Exception:
                profiler_data['system'] = {'error': 'psutil not available'}
            
            cache.set(cache_key, profiler_data, timeout=300)
        except Exception as e:
            current_app.logger.exception('profiler error')
            profiler_data['error'] = 'حدث خطأ داخلي'
    else:
        profiler_data = cached_data
    
    return render_template('advanced/performance_profiler.html', profiler_data=profiler_data)


@advanced_bp.route('/database-optimizer', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_HEALTH)
def database_optimizer():
    """Database Optimizer - تحسين قاعدة البيانات"""
    from sqlalchemy import text
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'optimize':
            try:
                try:
                    db.session.rollback()
                except Exception:
                    current_app.logger.warning('rollback after error failed silently in advanced_control.py', exc_info=True)
                with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                    conn.execute(text("VACUUM (ANALYZE)"))
                flash('✅ تم تحسين قاعدة البيانات بنجاح', 'success')
                cache.delete("performance_profiler_data")
                cache.delete("total_records_count")
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception('internal error')
                flash('حدث خطأ داخلي', 'danger')
            return redirect(url_for('advanced.database_optimizer'))
        
        elif action == 'analyze':
            try:
                db.session.execute(text("ANALYZE"))
                db.session.commit()
                flash('✅ تم تحليل قاعدة البيانات', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception('internal error')
                flash('حدث خطأ داخلي', 'danger')
            return redirect(url_for('advanced.database_optimizer'))
        
        elif action == 'reindex':
            try:
                inspector = inspect(db.engine)
                tables = list(inspector.get_table_names() or [])
                
                reindexed = []
                dialect = getattr(db.engine, "dialect", None)
                preparer = getattr(dialect, "identifier_preparer", None)
                for table in tables:
                    try:
                        quoted = preparer.quote(table) if preparer else table
                        db.session.execute(text(f"REINDEX TABLE {quoted}"))
                        reindexed.append(table)
                    except Exception:
                        continue
                
                db.session.commit()
                flash(f'✅ تم إعادة فهرسة {len(reindexed)} جدول', 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception('internal error')
                flash('حدث خطأ داخلي', 'danger')
            return redirect(url_for('advanced.database_optimizer'))
    
    try:
        try:
            result = db.session.execute(text("SELECT pg_database_size(current_database())")).scalar()
            db_size = float(result) / (1024 * 1024) if result else 0
        except Exception:
            db_size = 0
        db_location = db.engine.url.database or 'N/A'
        
        inspector = inspect(db.engine)
        tables = list(inspector.get_table_names() or [])
        
        index_count = 0
        for table in tables:
            try:
                import warnings
                from sqlalchemy.exc import SAWarning
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="Skipped unsupported reflection of expression-based index.*",
                        category=SAWarning,
                    )
                    indexes = inspector.get_indexes(table)
                index_count += len(indexes)
            except Exception:
                continue
        
        stats = {
            'db_size_mb': round(db_size, 2),
            'table_count': len(tables),
            'index_count': index_count,
            'db_path': db_location
        }
    except Exception as e:
        current_app.logger.exception('database optimizer error')
        stats = {'error': 'حدث خطأ داخلي'}
    
    template = """
    {% extends 'base.html' %}
    {% block title %}Database Optimizer{% endblock %}
    {% block page_title %}🛠️ Database Optimizer{% endblock %}
    {% block content %}
    <div class="container-fluid">
      {% include 'advanced/_navigation.html' %}
      {% if stats.error %}
        <div class="alert alert-danger border-0 shadow-sm mb-4">{{ stats.error }}</div>
      {% else %}
      <div class="row g-3 mb-4">
        <div class="col-md-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body">
              <div class="text-muted">حجم قاعدة البيانات</div>
              <div class="h3 mb-1">{{ stats.db_size_mb }} MB</div>
              <div class="small text-muted">{{ stats.db_path }}</div>
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body">
              <div class="text-muted">الجداول</div>
              <div class="h3 mb-1">{{ stats.table_count }}</div>
              <div class="small text-muted">إحصاء تقريبي</div>
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body">
              <div class="text-muted">الفهارس</div>
              <div class="h3 mb-1">{{ stats.index_count }}</div>
              <div class="small text-muted">حسب SQLAlchemy inspector</div>
            </div>
          </div>
        </div>
      </div>
      <div class="row g-3">
        <div class="col-md-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body text-center">
              <i class="fas fa-magic fa-3x text-success mb-3"></i>
              <h6>Optimize</h6>
              <p class="small text-muted mb-3">VACUUM (ANALYZE)</p>
              <form method="POST">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <input type="hidden" name="action" value="optimize">
                <button type="submit" class="btn btn-success w-100">تشغيل</button>
              </form>
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body text-center">
              <i class="fas fa-search fa-3x text-primary mb-3"></i>
              <h6>Analyze</h6>
              <p class="small text-muted mb-3">تحديث إحصائيات الاستعلامات</p>
              <form method="POST">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <input type="hidden" name="action" value="analyze">
                <button type="submit" class="btn btn-primary w-100">تشغيل</button>
              </form>
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card border-0 shadow-sm h-100">
            <div class="card-body text-center">
              <i class="fas fa-stream fa-3x text-warning mb-3"></i>
              <h6>Reindex</h6>
              <p class="small text-muted mb-3">REINDEX (PostgreSQL)</p>
              <form method="POST">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <input type="hidden" name="action" value="reindex">
                <button type="submit" class="btn btn-warning w-100 text-white">تشغيل</button>
              </form>
            </div>
          </div>
        </div>
      </div>
      {% endif %}
    </div>
    {% endblock %}
    """
    return render_template_string(template, stats=stats)


@advanced_bp.route('/api/performance/stats', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_SYSTEM_HEALTH)
def api_performance_stats():
    """API للحصول على إحصائيات الأداء"""
    from sqlalchemy import text
    import time
    
    try:
        start = time.time()
        db.session.execute(text("SELECT 1"))
        query_time = (time.time() - start) * 1000
        
        dialect = getattr(db.engine, "dialect", None)
        dialect_name = (getattr(dialect, "name", "") or "").lower()
        if dialect_name != "postgresql":
            return jsonify({
                'success': False,
                'error': 'performance_stats.postgresql_only',
                'stats': {
                    'query_time_ms': round(query_time, 2),
                    'db_size_mb': None,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            })

        size_bytes = db.session.execute(text("SELECT pg_database_size(current_database())")).scalar()
        db_size = (float(size_bytes) / (1024 * 1024)) if size_bytes else 0
        
        return jsonify({
            'success': True,
            'stats': {
                'query_time_ms': round(query_time, 2),
                'db_size_mb': round(db_size, 2),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        })
    except Exception as e:
        current_app.logger.exception('API error')
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500
