from __future__ import annotations

import json
import re
from typing import Any, Dict

from flask import abort, jsonify, request
from models import SystemSettings

DANGEROUS_METHODS = {"TRACE", "TRACK"}
MAX_FIELD_LEN = 10000
SUSPICIOUS_PATTERNS = (
    re.compile(r"(?is)<\s*script\b"),
    re.compile(r"(?is)javascript\s*:"),
    re.compile(r"(?is)on\w+\s*="),
    re.compile(r"(?is)\bunion\s+select\b"),
    re.compile(r"(?is)\b(drop|truncate|alter)\s+(table|database)\b"),
    re.compile(r"(?is)\.\./"),
)


def get_client_ip():
    """Return client IP using Flask's trusted proxy chain.

    When running behind a reverse proxy, configure
    ``werkzeug.middleware.proxy_fix.ProxyFix`` on the WSGI app so that
    ``request.remote_addr`` already reflects the real client IP.
    This avoids blindly trusting the ``X-Forwarded-For`` header which
    can be spoofed to bypass rate-limiting and IP-based access controls.
    """
    return request.remote_addr or "0.0.0.0"


def _log_security_event(event: str, data: Dict[str, Any] = None) -> None:
    try:
        from utils.security import log_security_event
        log_security_event(event, data or {})
    except Exception:
        try:
            from AI.engine.ai_storage import append_json_list, utc_now
            append_json_list("security_middleware_events.json", {"timestamp": utc_now(), "event": event, "data": data or {}, "ip": get_client_ip(), "path": request.path}, max_items=1000)
        except Exception:
            pass


def _setting_bool(key: str, default: bool = False) -> bool:
    try:
        return str(SystemSettings.get_setting(key, default)).strip().lower() in {"1", "true", "yes", "on", "enabled"}
    except Exception:
        return default


def _is_suspicious_value(value: Any) -> bool:
    text = str(value or "")
    if len(text) > MAX_FIELD_LEN:
        return True
    if not text:
        return False
    return any(pattern.search(text) for pattern in SUSPICIOUS_PATTERNS)


def _iter_request_values():
    for key, value in request.args.items():
        yield f"query:{key}", value
    if request.form:
        for key, value in request.form.items():
            yield f"form:{key}", value
    if request.is_json:
        try:
            payload = request.get_json(silent=True)
        except Exception:
            payload = None
        stack = [("json", payload)]
        while stack:
            prefix, current = stack.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    stack.append((f"{prefix}.{key}", value))
            elif isinstance(current, list):
                for idx, value in enumerate(current[:50]):
                    stack.append((f"{prefix}[{idx}]", value))
            else:
                yield prefix, current


def request_safety_middleware():
    if request.method in DANGEROUS_METHODS:
        _log_security_event("dangerous_http_method", {"method": request.method})
        abort(405)

    if request.endpoint and request.endpoint.startswith("static"):
        return None

    for key, value in _iter_request_values():
        if _is_suspicious_value(value):
            _log_security_event("suspicious_request_value", {"field": key, "sample": str(value)[:200]})
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({"success": False, "error": "طلب غير آمن أو يحتوي بيانات غير مقبولة"}), 400
            abort(400)
    return None


def check_ip_allowed(ip):
    try:
        from extensions import db
        # Ensure we are not in a failed transaction state
        if db.session.is_active:
            try:
                db.session.rollback()
            except Exception:
                pass

        enable_whitelist = SystemSettings.get_setting('enable_ip_whitelist', False)
        enable_blacklist = SystemSettings.get_setting('enable_ip_blacklist', False)
        enable_country_block = SystemSettings.get_setting('enable_country_blocking', False)
    except Exception as e:
        # Fallback if DB access fails
        try:
            current_app.logger.error("Middleware Security Check Failed: %s", e)
        except Exception:
            logger.error("Middleware Security Check Failed: %s", e)
        return {'allowed': True, 'reason': 'Security check bypassed due to DB error'}
    
    if not any([enable_whitelist, enable_blacklist, enable_country_block]):
        return {'allowed': True, 'reason': 'Security checks disabled'}
    
    if enable_blacklist:
        blacklist_raw = SystemSettings.get_setting('ip_blacklist', '[]')
        try:
            blacklist = json.loads(blacklist_raw) if isinstance(blacklist_raw, str) else blacklist_raw
        except Exception:
            blacklist = []
        
        if ip in blacklist:
            return {'allowed': False, 'reason': 'IP في القائمة السوداء'}
    
    if enable_whitelist:
        whitelist_raw = SystemSettings.get_setting('ip_whitelist', '[]')
        try:
            whitelist = json.loads(whitelist_raw) if isinstance(whitelist_raw, str) else whitelist_raw
        except Exception:
            whitelist = []
        
        if ip not in whitelist:
            return {'allowed': False, 'reason': 'IP غير موجود في القائمة البيضاء'}
    
    if enable_country_block:
        try:
            import ipaddress
            import requests
            try:
                ip_obj = ipaddress.ip_address(str(ip))
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved or ip_obj.is_link_local:
                    return {'allowed': True, 'reason': 'Local IP bypassed country block'}
            except Exception:
                pass
            
            response = requests.get(f'https://ip-api.com/json/{ip}?fields=countryCode', timeout=2)
            if response.status_code == 200:
                data = response.json()
                country_code = data.get('countryCode', '')
                
                blocked_countries_raw = SystemSettings.get_setting('blocked_countries', '[]')
                try:
                    blocked_countries = json.loads(blocked_countries_raw) if isinstance(blocked_countries_raw, str) else blocked_countries_raw
                except Exception:
                    blocked_countries = []
                
                if country_code in blocked_countries:
                    return {'allowed': False, 'reason': f'الدولة {country_code} محظورة'}
        except Exception:
            pass
    
    return {'allowed': True, 'reason': 'مسموح'}


def ip_security_middleware():
    if request.endpoint and (
        request.endpoint.startswith('auth.') or 
        request.endpoint.startswith('static') or
        request.endpoint.startswith('security_control.')
    ):
        return None
    
    client_ip = get_client_ip()
    result = check_ip_allowed(client_ip)
    
    if not result['allowed']:
        if request.is_json or request.path.startswith('/api/'):
            return jsonify({
                'error': 'Access Denied',
                'reason': result['reason'],
                'ip': client_ip
            }), 403
        else:
            abort(403)
    
    return None


def apply_security_headers(response):
    """Single authoritative location for security response headers.

    The ``_register_app_handlers`` function in *app.py* no longer sets
    these headers so there is no conflict or duplication.
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # X-XSS-Protection is deprecated; "0" disables the legacy XSS auditor
    # to avoid false-positive blocking that can itself be exploited.
    response.headers["X-XSS-Protection"] = "0"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def init_security_middleware(app):
    if getattr(app, "_azad_security_middleware_enabled", False):
        return

    @app.before_request
    def check_request_safety():
        return request_safety_middleware()

    @app.before_request
    def check_ip_security():
        return ip_security_middleware()

    @app.after_request
    def add_security_headers(response):
        return apply_security_headers(response)

    app._azad_security_middleware_enabled = True
