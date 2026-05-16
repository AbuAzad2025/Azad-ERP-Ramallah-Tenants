

from __future__ import annotations
import os
import sys
import time
import psutil
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any

from permissions_config.enums import SystemPermissions
from flask import Blueprint, jsonify, current_app
from flask_login import login_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from extensions import db, cache, socketio
from models import User, Product, ServiceRequest, Sale, Payment
from utils import permission_required

health_bp = Blueprint("health", __name__, url_prefix="/health")


def _check_database() -> Dict[str, Any]:
    try:
        start = time.time()
        result = db.session.execute(text("SELECT 1")).scalar()
        duration = time.time() - start

        if result == 1:
            # إحصائيات إضافية
            stats = {
                "status": "healthy",
                "response_time_ms": round(duration * 1000, 2),
                "type": "PostgreSQL",
            }

            try:
                from extensions import cache
                cache_key = 'health_records_stats'
                cached = cache.get(cache_key)
                if cached is not None:
                    stats["records"] = cached
                else:
                    stats["records"] = {
                        "users": db.session.query(User).count(),
                        "products": db.session.query(Product).count(),
                        "services": db.session.query(ServiceRequest).count(),
                        "sales": db.session.query(Sale).count(),
                        "payments": db.session.query(Payment).count(),
                    }
                    cache.set(cache_key, stats["records"], timeout=60)
            except Exception:
                pass

            return stats
        else:
            return {
                "status": "unhealthy",
                "error": "Database query returned unexpected result",
                "response_time_ms": round(duration * 1000, 2)
            }
    except SQLAlchemyError as e:
        try:
            current_app.logger.exception("Health database check failed")
        except Exception:
            pass
        return {
            "status": "unhealthy",
            "error": "database_error",
            "type": "database_error"
        }
    except Exception as e:
        try:
            current_app.logger.exception("Health database check failed")
        except Exception:
            pass
        return {
            "status": "unhealthy",
            "error": "unknown_error",
            "type": "unknown_error"
        }

def _check_cache() -> Dict[str, Any]:
    """فحص نظام التخزين المؤقت"""
    try:
        test_key = "health_check_test"
        test_value = str(time.time())

        start = time.time()
        cache.set(test_key, test_value, timeout=10)
        retrieved = cache.get(test_key)
        duration = time.time() - start

        if retrieved == test_value:
            cache.delete(test_key)
            return {
                "status": "healthy",
                "response_time_ms": round(duration * 1000, 2),
                "type": current_app.config.get("CACHE_TYPE", "simple")
            }
        else:
            return {
                "status": "degraded",
                "warning": "Cache read/write mismatch",
                "response_time_ms": round(duration * 1000, 2)
            }
    except Exception as e:
        try:
            current_app.logger.exception("Health cache check failed")
        except Exception:
            pass
        return {
            "status": "unhealthy",
            "error": "cache_error",
            "type": "cache_error"
        }

def _check_disk_space() -> Dict[str, Any]:
    """فحص المساحة المتوفرة على القرص"""
    try:
        instance_dir = current_app.instance_path or os.path.join(os.getcwd(), "instance")

        disk = psutil.disk_usage(instance_dir)

        status = "healthy"
        if disk.percent > 90:
            status = "critical"
        elif disk.percent > 80:
            status = "warning"

        return {
            "status": status,
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent_used": round(disk.percent, 2),
            "path": instance_dir
        }
    except Exception as e:
        return {
            "status": "unknown",
            "error": "disk_check_error"
        }

def _check_memory() -> Dict[str, Any]:
    """فحص استخدام الذاكرة"""
    try:
        process = psutil.Process()
        mem_info = process.memory_info()
        virtual_mem = psutil.virtual_memory()

        status = "healthy"
        if virtual_mem.percent > 90:
            status = "critical"
        elif virtual_mem.percent > 80:
            status = "warning"

        return {
            "status": status,
            "process_mb": round(mem_info.rss / (1024**2), 2),
            "system_total_gb": round(virtual_mem.total / (1024**3), 2),
            "system_used_gb": round(virtual_mem.used / (1024**3), 2),
            "system_available_gb": round(virtual_mem.available / (1024**3), 2),
            "system_percent": round(virtual_mem.percent, 2)
        }
    except Exception as e:
        return {
            "status": "unknown",
            "error": "memory_check_error"
        }

def _check_socketio() -> Dict[str, Any]:
    """فحص Socket.IO"""
    try:
        # فحص بسيط لوجود socketio
        if socketio:
            return {
                "status": "healthy",
                "async_mode": current_app.config.get("SOCKETIO_ASYNC_MODE", "unknown")
            }
        else:
            return {
                "status": "unavailable",
                "message": "Socket.IO not initialized"
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": "socketio_check_error"
        }

def _get_system_info() -> Dict[str, Any]:
    """معلومات النظام الأساسية"""
    try:
        return {
            "python_version": sys.version,
            "platform": sys.platform,
            "cpu_count": os.cpu_count(),
            "cpu_percent": psutil.cpu_percent(interval=0.1),
        }
    except Exception as e:
        return {
            "error": "system_info_error"
        }

@health_bp.route("/", methods=["GET"])
@health_bp.route("/status", methods=["GET"])
@login_required
@permission_required(SystemPermissions.MANAGE_SYSTEM_HEALTH)
def health_check():
    """
    نقطة نهاية فحص الصحة الشاملة
    Comprehensive health check endpoint

    Returns:
        JSON response with system health status
    """
    start_time = time.time()

    # جمع معلومات الصحة
    checks = {
        "database": _check_database(),
        "cache": _check_cache(),
        "disk": _check_disk_space(),
        "memory": _check_memory(),
        "socketio": _check_socketio(),
    }

    # تحديد الحالة الإجمالية
    overall_status = "healthy"
    for check_name, check_result in checks.items():
        check_status = check_result.get("status", "unknown")
        if check_status in ("unhealthy", "critical"):
            overall_status = "unhealthy"
            break
        elif check_status == "warning" and overall_status != "unhealthy":
            overall_status = "degraded"

    response = {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "version": current_app.config.get("APP_VERSION", "unknown"),
        "environment": current_app.config.get("APP_ENV", "unknown"),
        "checks": checks,
        "system": _get_system_info(),
        "response_time_ms": round((time.time() - start_time) * 1000, 2)
    }

    # تحديد HTTP status code بناءً على الحالة
    http_status = 200
    if overall_status == "unhealthy":
        http_status = 503  # Service Unavailable
    elif overall_status == "degraded":
        http_status = 200  # OK but with warnings

    return jsonify(response), http_status

@health_bp.route("/ping", methods=["GET"])
def ping():
    """
    فحص سريع للتأكد من أن التطبيق يعمل
    Quick ping check
    """
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "message": "pong"
    }), 200

@health_bp.route("/ready", methods=["GET"])
def readiness():
    """
    فحص الجاهزية - هل التطبيق جاهز لاستقبال الطلبات؟
    Readiness check - is the app ready to serve requests?
    """
    try:
        # فحص الاتصال بقاعدة البيانات فقط
        db.session.execute(text("SELECT 1")).scalar()

        return jsonify({
            "status": "ready",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }), 200
    except Exception:
        try:
            current_app.logger.exception("Readiness check failed")
        except Exception:
            pass
        return jsonify({
            "status": "not_ready",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "error": "readiness_check_failed"
        }), 503

@health_bp.route("/live", methods=["GET"])
def liveness():
    """
    فحص الحيوية - هل التطبيق لا يزال حياً؟
    Liveness check - is the app still alive?
    """
    return jsonify({
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }), 200

@health_bp.route("/metrics", methods=["GET"])
@login_required
@permission_required(SystemPermissions.MANAGE_SYSTEM_HEALTH)
def metrics():
    """
    مقاييس التطبيق
    Application metrics
    """
    try:
        process = psutil.Process()

        metrics_data = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "process": {
                "memory_rss_mb": round(process.memory_info().rss / (1024**2), 2),
                "memory_percent": round(process.memory_percent(), 2),
                "cpu_percent": round(process.cpu_percent(interval=0.1), 2),
                "num_threads": process.num_threads(),
                "create_time": datetime.fromtimestamp(process.create_time()).isoformat(),
            },
            "system": {
                "cpu_count": os.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "memory_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
                "memory_percent": round(psutil.virtual_memory().percent, 2),
            }
        }

        return jsonify(metrics_data), 200
    except Exception:
        try:
            current_app.logger.exception("Health metrics failed")
        except Exception:
            pass
        return jsonify({
            "error": "metrics_check_failed"
        }), 500

