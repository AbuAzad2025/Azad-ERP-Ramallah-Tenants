"""
👑 AI Admin Routes - مسارات تحكم المالك بالمساعد
════════════════════════════════════════════════════════════════════

وظيفة هذا الملف:
- إدارة صلاحيات المساعد
- إخفاء/إظهار للمستخدمين
- تحكم كامل من المالك

Created: 2025-11-01
"""

from permissions_config.enums import SystemPermissions
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from models import SystemSettings
from extensions import db
from utils import permission_required
import os
from pathlib import Path
from werkzeug.utils import secure_filename


# Blueprint
ai_admin_bp = Blueprint('ai_admin', __name__, url_prefix='/ai-admin')


@ai_admin_bp.before_request
def restrict_to_owner():
    """تقييد الوصول للمالك فقط"""
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    
    if not current_user.is_system:
        flash('⛔ هذه اللوحة خاصة بالمالك فقط', 'danger')
        return redirect(url_for('main.dashboard'))


# ═══════════════════════════════════════════════════════════════════════════
@ai_admin_bp.route('/config', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_AI)
def ai_config_dashboard():
    """
    لوحة تحكم إعدادات الذكاء الاصطناعي (Dashboard)
    تعرض حالة النظام والمفاتيح والتدريب
    """
    from AI.engine.ai_management import get_live_ai_stats, get_model_status
    
    # 1. إحصائيات النظام الحية
    try:
        stats = get_live_ai_stats()
    except:
        stats = {'status': 'unknown', 'latency': 'N/A', 'queries_today': 0}

    # 2. حالة النماذج
    try:
        model_status = get_model_status()
    except:
        model_status = {'last_trained': 'N/A'}

    return render_template(
        'security/ai_config.html',
        stats=stats,
        model_status=model_status
    )

@ai_admin_bp.route('/settings', methods=['GET', 'POST'])
@permission_required(SystemPermissions.MANAGE_AI)
def ai_settings():
    """
    إعدادات المساعد الذكي (للمالك فقط)
    
    يتحكم في:
    - تفعيل/تعطيل المساعد
    - من يرى المساعد (مدراء، موظفين، الكل)
    - صلاحيات التنفيذ
    """
    if request.method == 'POST':
        try:
            # حفظ الإعدادات
            settings = {
                'ai_enabled': request.form.get('ai_enabled') == 'on',
                'ai_visible_to_managers': request.form.get('ai_visible_to_managers') == 'on',
                'ai_visible_to_staff': request.form.get('ai_visible_to_staff') == 'on',
                'ai_visible_to_customers': request.form.get('ai_visible_to_customers') == 'on',
                'ai_can_execute_actions': request.form.get('ai_can_execute_actions') == 'on',
                'ai_realtime_alerts_enabled': request.form.get('ai_realtime_alerts_enabled') == 'on',
                'ai_auto_learning_enabled': request.form.get('ai_auto_learning_enabled') == 'on'
            }
            
            for key, value in settings.items():
                SystemSettings.set_setting(
                    key=key,
                    value=str(value),
                    data_type='boolean',
                    is_public=False
                )
            
            db.session.commit()
            
            flash('✅ تم حفظ إعدادات المساعد الذكي', 'success')
            return redirect(url_for('ai_admin.ai_settings'))
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('internal error')
            flash('حدث خطأ داخلي', 'danger')
    
    def to_bool(value, default):
        if value is None:
            value = default
        if isinstance(value, str):
            return value.lower() == 'true'
        return bool(value)
    
    current_settings = {
        'ai_enabled': to_bool(SystemSettings.get_setting('ai_enabled', True), True),
        'ai_visible_to_managers': to_bool(SystemSettings.get_setting('ai_visible_to_managers', True), True),
        'ai_visible_to_staff': to_bool(SystemSettings.get_setting('ai_visible_to_staff', False), False),
        'ai_visible_to_customers': to_bool(SystemSettings.get_setting('ai_visible_to_customers', False), False),
        'ai_can_execute_actions': to_bool(SystemSettings.get_setting('ai_can_execute_actions', True), True),
        'ai_realtime_alerts_enabled': to_bool(SystemSettings.get_setting('ai_realtime_alerts_enabled', True), True),
        'ai_auto_learning_enabled': to_bool(SystemSettings.get_setting('ai_auto_learning_enabled', True), True)
    }
    
    return render_template(
        'ai/ai_admin_settings.html',
        settings=current_settings
    )


@ai_admin_bp.route('/toggle-visibility', methods=['POST'])
@permission_required(SystemPermissions.MANAGE_AI)
def toggle_visibility():
    """
    تبديل إظهار/إخفاء المساعد (API)
    
    Body:
        {
            'visible': true/false
        }
    """
    try:
        data = request.get_json()
        visible = data.get('visible', True)
        
        SystemSettings.set_setting('ai_enabled', str(visible), data_type='boolean')
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم التحديث',
            'ai_enabled': visible
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/reset-knowledge', methods=['POST'])
@permission_required(SystemPermissions.TRAIN_AI)
def reset_knowledge():
    """
    إعادة بناء قاعدة المعرفة بالكامل - تدريب حقيقي
    
    يقوم بـ:
    1. فحص شامل لقاعدة البيانات (كل الجداول والحقول)
    2. فحص كل الموديلات
    3. فحص كل Routes
    4. فحص كل Forms
    5. فحص كل Templates
    6. تحليل العلاقات
    7. فحص Enums
    8. حفظ المعرفة في JSON
    """
    try:
        from AI.engine.ai_training_engine import get_training_engine
        import threading
        
        engine = get_training_engine()
        
        # فحص إذا كان التدريب يعمل
        status = engine.get_status()
        if status.get('running'):
            return jsonify({
                'success': False,
                'error': 'Training already in progress',
                'status': status
            }), 400
        
        # تشغيل التدريب في thread منفصل
        def run_training():
            from app import create_app
            app = create_app()
            with app.app_context():
                try:
                    engine.run_full_training(force=True)
                except Exception as e:
                    app.logger.error(f"Training error: {e}")
                finally:
                    db.session.remove()
        
        training_thread = threading.Thread(target=run_training, daemon=True)
        training_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'تم بدء التدريب - جارٍ المعالجة...',
            'status': engine.get_status()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/training-status', methods=['GET'])
@permission_required(SystemPermissions.TRAIN_AI)
def training_status():
    """الحصول على حالة التدريب"""
    try:
        from AI.engine.ai_training_engine import get_training_engine
        
        engine = get_training_engine()
        status = engine.get_status()
        
        return jsonify({
            'success': True,
            'status': status
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/training-log', methods=['GET'])
@permission_required(SystemPermissions.TRAIN_AI)
def training_log():
    """الحصول على سجل التدريب"""
    try:
        from AI.engine.ai_training_engine import get_training_engine
        
        engine = get_training_engine()
        limit = request.args.get('limit', 50, type=int)
        log = engine.get_training_log(limit=limit)
        
        return jsonify({
            'success': True,
            'log': log
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/daily-reports', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_AI)
def daily_reports():
    """عرض التقارير اليومية"""
    try:
        from pathlib import Path
        import os
        
        reports_dir = 'AI/data/daily_reports'
        
        if not os.path.exists(reports_dir):
            flash('⚠️ لا توجد تقارير يومية بعد', 'info')
            return render_template('ai/daily_reports.html', daily_reports=[])
        
        # قراءة التقارير
        reports = []
        for report_file in sorted(Path(reports_dir).glob('report_*.json'), reverse=True):
            try:
                with open(report_file, 'r', encoding='utf-8') as f:
                    report_data = json.load(f)
                    reports.append(report_data)
            except Exception:
                pass
        
        return render_template('ai/daily_reports.html', daily_reports=reports[:30])  # آخر 30 تقرير
    
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('ai_admin.ai_settings'))


@ai_admin_bp.route('/evolution-report', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_AI)
def evolution_report():
    """تقرير التطور الذاتي"""
    try:
        from AI.engine.ai_self_evolution import get_evolution_engine
        
        engine = get_evolution_engine()
        report = engine.get_evolution_report()
        suggestions = engine.suggest_improvements()
        
        return render_template(
            'ai/evolution_report.html',
            report=report,
            suggestions=suggestions
        )
    
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('ai_admin.ai_settings'))


@ai_admin_bp.route('/run-code-scan', methods=['POST'])
@permission_required(SystemPermissions.MANAGE_AI)
def run_code_scan():
    try:
        from AI.engine.ai_code_quality_monitor import get_code_monitor
        import threading
        
        def run_scan():
            from app import create_app
            app = create_app()
            with app.app_context():
                try:
                    monitor = get_code_monitor()
                    monitor.run_daily_scan()
                except Exception as e:
                    app.logger.error(f"Scan error: {e}")
                finally:
                    db.session.remove()
        
        scan_thread = threading.Thread(target=run_scan, daemon=True)
        scan_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'تم بدء الفحص'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/performance', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_AI)
def performance_report():
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        from AI.engine.ai_self_evolution import get_evolution_engine
        from AI.engine.ai_learning_system import get_learning_system
        
        tracker = get_performance_tracker()
        evolution = get_evolution_engine()
        learning = get_learning_system()
        
        perf_report = tracker.get_performance_report()
        evo_report = evolution.get_evolution_report()
        learning_stats = learning.get_learning_stats()
        
        return render_template(
            'ai/performance_report.html',
            performance=perf_report,
            evolution=evo_report,
            learning=learning_stats
        )
    
    except Exception as e:
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('ai_admin.ai_settings'))


@ai_admin_bp.route('/stats-api', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_AI)
def stats_api():
    try:
        from AI.engine.ai_performance_tracker import get_performance_tracker
        from AI.engine.ai_self_evolution import get_evolution_engine
        from AI.engine.ai_learning_system import get_learning_system
        
        tracker = get_performance_tracker()
        evolution = get_evolution_engine()
        learning = get_learning_system()
        
        return jsonify({
            'success': True,
            'performance': tracker.get_performance_report(),
            'evolution': evolution.get_evolution_report(),
            'learning': learning.get_learning_stats()
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        })


@ai_admin_bp.route('/advanced-training', methods=['GET'])
@permission_required(SystemPermissions.TRAIN_AI)
def advanced_training():
    """صفحة التدريب المتقدم"""
    return render_template('ai/advanced_training.html')


@ai_admin_bp.route('/command/<command_name>', methods=['POST'])
@permission_required(SystemPermissions.MANAGE_AI)
def execute_command(command_name):
    """تنفيذ أوامر النظام"""
    try:
        from AI.engine.ai_master_controller import get_master_controller
        
        controller = get_master_controller()
        
        params = request.get_json() or {}
        
        result = controller.execute_system_command(command_name, params)
        
        return jsonify({
            'success': result.get('success', True),
            'result': result,
            'error': result.get('error')
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/upload_book', methods=['POST'])
@permission_required(SystemPermissions.TRAIN_AI)
def upload_book():
    """رفع وقراءة كتاب"""
    try:
        if 'book_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        file = request.files['book_file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        filename = secure_filename(file.filename)
        books_dir = Path('AI/data/books')
        books_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = books_dir / filename
        file.save(file_path)
        
        file_format = 'pdf' if filename.lower().endswith('.pdf') else 'markdown'
        
        from AI.engine.ai_master_controller import get_master_controller
        
        controller = get_master_controller()
        result = controller.execute_system_command('read_book', {
            'file_path': str(file_path),
            'format': file_format
        })
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'title': result.get('title'),
                'chapters': result.get('chapters'),
                'pages': result.get('pages'),
                'key_concepts': result.get('key_concepts'),
                'key_terms': result.get('key_terms')
            })
        else:
            return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/memory_stats', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_AI)
def memory_stats():
    """إحصائيات الذاكرة"""
    try:
        from AI.engine.ai_deep_memory import get_deep_memory
        
        memory = get_deep_memory()
        stats = memory.get_memory_stats()
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/system_status', methods=['GET'])
@permission_required(SystemPermissions.MANAGE_AI)
def system_status():
    """حالة النظام"""
    try:
        from AI.engine.ai_master_controller import get_master_controller
        
        controller = get_master_controller()
        status = controller.get_system_status()
        
        return jsonify({
            'success': True,
            'status': status
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/train-package', methods=['POST'])
@permission_required(SystemPermissions.TRAIN_AI)
def train_package():
    """تدريب باقة متخصصة"""
    try:
        data = request.get_json()
        package_id = data.get('package_id')
        
        from AI.engine.ai_specialized_training import get_specialized_training
        
        trainer = get_specialized_training()
        result = trainer.train_package(package_id)
        
        if result.get('success'):
            return jsonify({
                'success': True,
                'package_name': trainer.training_packages.get(package_id, {}).get('name'),
                'items_learned': result.get('items_learned', 0)
            })
        else:
            return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/train-all-packages', methods=['POST'])
@permission_required(SystemPermissions.TRAIN_AI)
def train_all_packages():
    """تدريب جميع الباقات"""
    try:
        from AI.engine.ai_specialized_training import get_specialized_training
        
        trainer = get_specialized_training()
        result = trainer.train_all_packages()
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


@ai_admin_bp.route('/marathon-training', methods=['POST'])
@permission_required(SystemPermissions.TRAIN_AI)
def marathon_training():
    """تدريب ماراثوني شامل"""
    try:
        import threading
        
        def run_marathon():
            from app import create_app
            app = create_app()
            with app.app_context():
                from AI.engine.ai_intensive_trainer import get_intensive_trainer
                from AI.engine.ai_specialized_training import get_specialized_training
                from AI.engine.ai_marathon_trainer import get_marathon_trainer
                from AI.engine.ai_heavy_equipment_expert import get_heavy_equipment_expert
                from AI.engine.ai_system_deep_trainer import get_system_deep_trainer
                
                try:
                    intensive = get_intensive_trainer()
                    intensive.start_intensive_training()
                    
                    specialized = get_specialized_training()
                    specialized.train_all_packages()
                    
                    marathon = get_marathon_trainer()
                    marathon.start_marathon_training()
                    
                    he_expert = get_heavy_equipment_expert()
                    he_expert.train_comprehensive()
                    
                    sys_trainer = get_system_deep_trainer()
                    sys_trainer.train_system_comprehensive()
                except Exception as e:
                    app.logger.error(f"Marathon training error: {e}")
                finally:
                    db.session.remove()
        
        marathon_thread = threading.Thread(target=run_marathon, daemon=True)
        marathon_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Marathon training started in background'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': 'حدث خطأ داخلي'
        }), 500


__all__ = ['ai_admin_bp']

