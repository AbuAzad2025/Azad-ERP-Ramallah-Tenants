"""AI Accounting and Control Auditor.

Professional financial, operational, and administrative auditor for the AI
assistant. It validates individual transactions and can scan recent user/system
activity for risk indicators such as unusual deletions, reversed transactions,
invalid payments, duplicate entries, negative stock, suspicious permission
changes, and other control weaknesses.

Important: this module reports risk indicators and control findings. It does not
accuse any user of theft or fraud; human review is required for final judgment.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

AUDIT_LOG_FILE = "accounting_audit_log.json"
CONTROL_AUDIT_LOG_FILE = "control_audit_log.json"
MAX_AUDIT_LOG = 500
MAX_FINDINGS = 500

RISK_WEIGHTS = {"LOW": 1, "MEDIUM": 3, "HIGH": 6, "CRITICAL": 10}
DEFAULT_THRESHOLDS = {
    "large_payment_amount": 5000,
    "large_expense_amount": 2000,
    "large_discount_percent": 30,
    "max_deletions_per_user": 5,
    "max_failed_logins_per_user": 5,
    "max_failed_logins_per_ip": 10,
    "max_voids_or_cancellations_per_user": 5,
    "duplicate_window_hours": 24,
    "lookback_days": 7,
}


def _decimal(value, default="0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _entry_amount(entry: Dict, *names: str) -> Decimal:
    for name in names:
        if name in entry:
            return _decimal(entry.get(name))
    return Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _value(obj: Any, *names: str, default=None):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _is_blank(value: Any) -> bool:
    return value in (None, "", [], {})


def _model_exists(name: str) -> bool:
    try:
        import models
        return getattr(models, name, None) is not None
    except Exception:
        return False


def _get_model(name: str):
    try:
        import models
        return getattr(models, name, None)
    except Exception:
        return None


def _date_col(model):
    for col_name in ("created_at", "updated_at", "payment_date", "sale_date", "invoice_date", "date", "archived_at"):
        col = getattr(model, col_name, None)
        if col is not None:
            return col
    return None


def _within_days_query(model, days: int):
    q = model.query
    col = _date_col(model)
    if col is not None:
        q = q.filter(col >= _now() - timedelta(days=max(1, int(days or 1))))
    return q


def _setting_threshold(key: str, default: Any) -> Any:
    try:
        from models import SystemSettings
        return SystemSettings.get_setting(f"ai_control_audit_{key}", default)
    except Exception:
        return default


def _thresholds() -> Dict[str, Any]:
    return {key: _setting_threshold(key, value) for key, value in DEFAULT_THRESHOLDS.items()}


def _record_identity(record: Any) -> Dict[str, Any]:
    return {
        "model": record.__class__.__name__,
        "id": getattr(record, "id", None),
        "created_at": _iso(_value(record, "created_at", "date", "payment_date", "sale_date", "invoice_date")),
        "updated_at": _iso(_value(record, "updated_at")),
    }


class AccountingAuditor:
    def __init__(self):
        self.audit_log = []
        self.control_audit_log = []
        self.detected_errors = []
        self.suspicious_transactions = []
        self._load_audit_log()
        self._load_control_audit_log()

    def _load_audit_log(self):
        data = read_json(AUDIT_LOG_FILE, {})
        if isinstance(data, dict):
            log = data.get("audit_log", [])
            self.audit_log = log[-MAX_AUDIT_LOG:] if isinstance(log, list) else []
            self.detected_errors = [audit for audit in self.audit_log if audit.get("status") == "fail"]

    def _load_control_audit_log(self):
        data = read_json(CONTROL_AUDIT_LOG_FILE, {})
        if isinstance(data, dict):
            log = data.get("control_audit_log", [])
            self.control_audit_log = log[-MAX_AUDIT_LOG:] if isinstance(log, list) else []

    def audit_transaction(self, transaction_type: str, data: Dict) -> Dict:
        audit = {"transaction_type": transaction_type, "timestamp": datetime.now().isoformat(), "status": "pass", "errors": [], "warnings": [], "recommendations": []}
        transaction_type = str(transaction_type or "").lower()
        if transaction_type == "sale":
            self._audit_sale_transaction(data or {}, audit)
        elif transaction_type == "payment":
            self._audit_payment_transaction(data or {}, audit)
        elif transaction_type == "gl_batch":
            self._audit_gl_batch(data or {}, audit)
        elif transaction_type == "stock_adjustment":
            self._audit_stock_adjustment(data or {}, audit)
        if audit["errors"]:
            audit["status"] = "fail"
            self.detected_errors.append(audit)
            self._alert_owner(audit)
        self.audit_log.append(audit)
        self.audit_log = self.audit_log[-MAX_AUDIT_LOG:]
        self.detected_errors = self.detected_errors[-MAX_AUDIT_LOG:]
        self._save_audit_log()
        return audit

    def run_control_audit(self, days: Optional[int] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Scan recent system activity and return professional control findings."""
        limits = _thresholds()
        days = _safe_int(days, _safe_int(limits.get("lookback_days"), 7))
        report = {
            "audit_type": "financial_operational_administrative_control",
            "generated_at": _now().isoformat(),
            "lookback_days": days,
            "user_id": user_id,
            "status": "clean",
            "risk_score": 0,
            "risk_level": "LOW",
            "findings": [],
            "summary": {},
            "recommendations": [],
            "disclaimer": "هذه مؤشرات رقابية تحتاج مراجعة بشرية ولا تمثل اتهاماً لأي مستخدم.",
        }

        self._scan_auth_risks(report, days, user_id, limits)
        self._scan_audit_log_risks(report, days, user_id, limits)
        self._scan_archive_risks(report, days, user_id, limits)
        self._scan_payment_risks(report, days, user_id, limits)
        self._scan_expense_risks(report, days, user_id, limits)
        self._scan_sales_invoice_risks(report, days, user_id, limits)
        self._scan_stock_product_risks(report, days, user_id, limits)
        self._scan_permission_risks(report, days, user_id, limits)

        self._finalize_control_report(report)
        self.control_audit_log.append(report)
        self.control_audit_log = self.control_audit_log[-MAX_AUDIT_LOG:]
        self._save_control_audit_log()
        return report

    def audit_user_activity(self, user_id: int, days: Optional[int] = None) -> Dict[str, Any]:
        return self.run_control_audit(days=days, user_id=user_id)

    def _add_finding(self, report: Dict[str, Any], *, code: str, severity: str, title: str, message: str, evidence: Optional[Dict] = None, recommendation: Optional[str] = None, user_id: Optional[int] = None, model: Optional[str] = None, record_id: Optional[int] = None) -> None:
        severity = str(severity or "LOW").upper()
        finding = {
            "code": code,
            "severity": severity if severity in RISK_WEIGHTS else "LOW",
            "title": title,
            "message": message,
            "user_id": user_id,
            "model": model,
            "record_id": record_id,
            "evidence": evidence or {},
            "recommendation": recommendation or "مراجعة بشرية للبيانات والسندات المرتبطة.",
            "created_at": _now().isoformat(),
        }
        report["findings"].append(finding)
        report["risk_score"] += RISK_WEIGHTS.get(finding["severity"], 1)
        if len(report["findings"]) > MAX_FINDINGS:
            report["findings"] = report["findings"][-MAX_FINDINGS:]

    def _scan_auth_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        AuthAudit = _get_model("AuthAudit")
        if AuthAudit is None:
            return
        try:
            q = _within_days_query(AuthAudit, days)
            if user_id and hasattr(AuthAudit, "user_id"):
                q = q.filter(AuthAudit.user_id == user_id)
            rows = q.limit(5000).all()
            failed_by_user = Counter()
            failed_by_ip = Counter()
            sensitive_events = []
            for row in rows:
                success = bool(getattr(row, "success", True))
                event = str(getattr(row, "event", "") or "")
                uid = getattr(row, "user_id", None)
                ip = getattr(row, "ip", None)
                if not success or "FAIL" in event.upper():
                    failed_by_user[uid] += 1
                    failed_by_ip[ip] += 1
                if any(term in event.upper() for term in ["ROLE", "PERM", "PASSWORD", "DEACTIVATE", "ACTIVATE"]):
                    sensitive_events.append(row)

            max_user_fails = _safe_int(limits.get("max_failed_logins_per_user"), 5)
            for uid, count in failed_by_user.items():
                if uid and count >= max_user_fails:
                    self._add_finding(report, code="AUTH_FAILED_LOGINS_USER", severity="HIGH", title="محاولات دخول فاشلة كثيرة", message=f"المستخدم رقم {uid} لديه {count} محاولة دخول فاشلة خلال آخر {days} أيام.", evidence={"failed_count": count}, recommendation="راجع الجهاز/IP والصلاحيات واحتمال محاولة تخمين كلمة مرور.", user_id=uid)
            max_ip_fails = _safe_int(limits.get("max_failed_logins_per_ip"), 10)
            for ip, count in failed_by_ip.items():
                if ip and count >= max_ip_fails:
                    self._add_finding(report, code="AUTH_FAILED_LOGINS_IP", severity="HIGH", title="محاولات دخول فاشلة من نفس IP", message=f"العنوان {ip} لديه {count} محاولة دخول فاشلة خلال آخر {days} أيام.", evidence={"ip": ip, "failed_count": count}, recommendation="راجع مصدر الاتصال وربما أضف حظر/تقييد مؤقت إذا كان غير معروف.")
            for row in sensitive_events[:100]:
                self._add_finding(report, code="AUTH_SENSITIVE_EVENT", severity="MEDIUM", title="حدث صلاحيات/كلمة مرور حساس", message=f"تم تسجيل حدث حساس: {getattr(row, 'event', '')}", evidence={"event": getattr(row, "event", None), "note": getattr(row, "note", None), "ip": getattr(row, "ip", None), "at": _iso(getattr(row, "created_at", None))}, recommendation="تأكد أن الحدث مصرح وموافق عليه إداريًا.", user_id=getattr(row, "user_id", None), model="AuthAudit", record_id=getattr(row, "id", None))
        except Exception as exc:
            report.setdefault("warnings", []).append(f"Auth audit scan failed: {exc}")

    def _scan_audit_log_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        AuditLog = _get_model("AuditLog")
        if AuditLog is None:
            return
        try:
            q = _within_days_query(AuditLog, days)
            if user_id and hasattr(AuditLog, "user_id"):
                q = q.filter(AuditLog.user_id == user_id)
            rows = q.order_by(getattr(AuditLog, "created_at", getattr(AuditLog, "id")).desc()).limit(5000).all()
            destructive_by_user = Counter()
            cancellation_by_user = Counter()
            settings_events = []
            for row in rows:
                action = str(_value(row, "action", "event", "operation", default="") or "").lower()
                uid = _value(row, "user_id", "actor_id")
                if any(term in action for term in ["delete", "حذف", "archive", "restore", "void", "cancel", "reverse"]):
                    destructive_by_user[uid] += 1
                if any(term in action for term in ["cancel", "void", "refund", "reverse", "return", "الغاء", "إلغاء"]):
                    cancellation_by_user[uid] += 1
                if any(term in action for term in ["setting", "permission", "role", "user", "system", "security"]):
                    settings_events.append(row)

            max_del = _safe_int(limits.get("max_deletions_per_user"), 5)
            for uid, count in destructive_by_user.items():
                if uid and count >= max_del:
                    self._add_finding(report, code="MANY_DESTRUCTIVE_ACTIONS", severity="CRITICAL", title="حركات حذف/إلغاء/أرشفة كثيرة", message=f"المستخدم رقم {uid} نفذ {count} حركة حساسة خلال آخر {days} أيام.", evidence={"count": count}, recommendation="راجع السجلات والسندات قبل اعتماد هذه الحركات، وفعّل مبدأ موافقة ثانية للحذف والإلغاء.", user_id=uid)
            max_cancel = _safe_int(limits.get("max_voids_or_cancellations_per_user"), 5)
            for uid, count in cancellation_by_user.items():
                if uid and count >= max_cancel:
                    self._add_finding(report, code="MANY_CANCELLATIONS", severity="HIGH", title="إلغاءات/عكس حركات كثيرة", message=f"المستخدم رقم {uid} لديه {count} حركة إلغاء/عكس/استرجاع.", evidence={"count": count}, recommendation="افحص أسباب الإلغاء وهل تتكرر على نفس الزبون أو نفس المبلغ.", user_id=uid)
            for row in settings_events[:100]:
                self._add_finding(report, code="SYSTEM_ADMIN_CHANGE", severity="HIGH", title="تغيير إداري أو أمني حساس", message=f"حركة إدارية حساسة: {_value(row, 'action', 'event', default='')}", evidence={"at": _iso(_value(row, "created_at")), "details": str(_value(row, "details", "description", "message", default=""))[:500]}, recommendation="راجع من أعطى الصلاحية ولماذا، واحتفظ بموافقة مكتوبة للتغييرات الحساسة.", user_id=_value(row, "user_id", "actor_id"), model="AuditLog", record_id=getattr(row, "id", None))
        except Exception as exc:
            report.setdefault("warnings", []).append(f"AuditLog scan failed: {exc}")

    def _scan_archive_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        Archive = _get_model("Archive")
        if Archive is None:
            return
        try:
            q = _within_days_query(Archive, days)
            if user_id and hasattr(Archive, "archived_by"):
                q = q.filter(Archive.archived_by == user_id)
            rows = q.limit(5000).all()
            by_user = Counter(getattr(row, "archived_by", None) for row in rows)
            max_del = _safe_int(limits.get("max_deletions_per_user"), 5)
            for uid, count in by_user.items():
                if uid and count >= max_del:
                    self._add_finding(report, code="MANY_ARCHIVES", severity="HIGH", title="أرشفة/حذف سجلات بكثرة", message=f"المستخدم رقم {uid} أرشف {count} سجل خلال آخر {days} أيام.", evidence={"count": count}, recommendation="راجع أسباب الأرشفة وتأكد من وجود صلاحية وموافقة، خصوصًا للسجلات المالية.", user_id=uid)
            for row in rows[:200]:
                reason = getattr(row, "archive_reason", None)
                table = getattr(row, "table_name", "")
                if _is_blank(reason) and any(t in str(table).lower() for t in ["payment", "sale", "invoice", "expense", "check"]):
                    self._add_finding(report, code="FINANCIAL_ARCHIVE_NO_REASON", severity="HIGH", title="أرشفة سجل مالي بدون سبب", message=f"تمت أرشفة سجل من {table} بدون سبب واضح.", evidence={"table": table, "record_id": getattr(row, "record_id", None), "at": _iso(getattr(row, "archived_at", None))}, recommendation="اجعل سبب الأرشفة إلزامياً للسجلات المالية.", user_id=getattr(row, "archived_by", None), model="Archive", record_id=getattr(row, "id", None))
        except Exception as exc:
            report.setdefault("warnings", []).append(f"Archive scan failed: {exc}")

    def _scan_payment_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        Payment = _get_model("Payment")
        if Payment is None:
            return
        try:
            q = _within_days_query(Payment, days)
            if user_id:
                user_col = getattr(Payment, "created_by", None) or getattr(Payment, "user_id", None)
                if user_col is not None:
                    q = q.filter(user_col == user_id)
            rows = q.limit(10000).all()
            seen = defaultdict(list)
            large_threshold = _decimal(limits.get("large_payment_amount", 5000))
            for row in rows:
                amount = _decimal(_value(row, "total_amount", "amount"))
                direction = str(_value(row, "direction", default="") or "").upper()
                status = str(_value(row, "status", default="") or "").upper()
                ref = _value(row, "reference", "ref", "check_number", default=None)
                uid = _value(row, "created_by", "user_id")
                entity_type = str(_value(row, "entity_type", default="") or "")
                date_val = _value(row, "payment_date", "created_at")
                if amount <= 0:
                    self._add_finding(report, code="PAYMENT_NON_POSITIVE", severity="CRITICAL", title="دفعة بمبلغ غير صالح", message="تم العثور على دفعة بمبلغ صفر أو سالب.", evidence={**_record_identity(row), "amount": float(amount)}, recommendation="امنع حفظ الدفعات بمبلغ غير موجب وراجع القيد المرتبط.", user_id=uid, model="Payment", record_id=getattr(row, "id", None))
                if direction not in {"IN", "OUT"}:
                    self._add_finding(report, code="PAYMENT_BAD_DIRECTION", severity="HIGH", title="دفعة بدون اتجاه صحيح", message="اتجاه الدفعة ليس IN أو OUT.", evidence={**_record_identity(row), "direction": direction}, recommendation="اجعل اتجاه الدفعة إلزامياً وواضحاً لأنه يؤثر على الرصيد.", user_id=uid, model="Payment", record_id=getattr(row, "id", None))
                if amount >= large_threshold:
                    self._add_finding(report, code="PAYMENT_LARGE_AMOUNT", severity="MEDIUM", title="دفعة كبيرة تحتاج مراجعة", message=f"دفعة بقيمة {amount} تتجاوز حد التنبيه {large_threshold}.", evidence={**_record_identity(row), "amount": float(amount), "direction": direction, "status": status}, recommendation="راجع السند والجهة وطريقة الدفع قبل اعتمادها.", user_id=uid, model="Payment", record_id=getattr(row, "id", None))
                if _is_blank(ref) and amount >= large_threshold:
                    self._add_finding(report, code="PAYMENT_LARGE_NO_REFERENCE", severity="HIGH", title="دفعة كبيرة بدون مرجع", message="دفعة كبيرة لا تحتوي مرجع/رقم سند واضح.", evidence={**_record_identity(row), "amount": float(amount)}, recommendation="اجعل المرجع إلزامياً للدفعات الكبيرة أو غير النقدية.", user_id=uid, model="Payment", record_id=getattr(row, "id", None))
                key = (str(date_val)[:10], entity_type, direction, float(amount), str(ref or ""))
                seen[key].append(row)
            for key, items in seen.items():
                if len(items) > 1 and key[3] > 0:
                    self._add_finding(report, code="POSSIBLE_DUPLICATE_PAYMENT", severity="HIGH", title="دفعات مكررة محتملة", message=f"تم العثور على {len(items)} دفعات متشابهة بنفس التاريخ/الجهة/الاتجاه/المبلغ/المرجع.", evidence={"key": key, "payment_ids": [getattr(i, "id", None) for i in items[:10]]}, recommendation="راجع احتمال التكرار قبل التسوية أو اعتماد كشف الحساب.", user_id=_value(items[0], "created_by", "user_id"), model="Payment")
        except Exception as exc:
            report.setdefault("warnings", []).append(f"Payment scan failed: {exc}")

    def _scan_expense_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        Expense = _get_model("Expense")
        if Expense is None:
            return
        try:
            q = _within_days_query(Expense, days)
            if user_id:
                user_col = getattr(Expense, "created_by", None) or getattr(Expense, "user_id", None)
                if user_col is not None:
                    q = q.filter(user_col == user_id)
            rows = q.limit(10000).all()
            seen = defaultdict(list)
            large_threshold = _decimal(limits.get("large_expense_amount", 2000))
            for row in rows:
                amount = _decimal(_value(row, "amount", "total_amount"))
                desc = _value(row, "description", "notes", "note", default="")
                ref = _value(row, "reference", "ref", default=None)
                uid = _value(row, "created_by", "user_id")
                date_val = _value(row, "date", "created_at")
                if amount <= 0:
                    self._add_finding(report, code="EXPENSE_NON_POSITIVE", severity="CRITICAL", title="مصروف بمبلغ غير صالح", message="مصروف بمبلغ صفر أو سالب.", evidence={**_record_identity(row), "amount": float(amount)}, recommendation="امنع حفظ المصاريف غير الموجبة وراجع أثرها المالي.", user_id=uid, model="Expense", record_id=getattr(row, "id", None))
                if amount >= large_threshold and _is_blank(ref):
                    self._add_finding(report, code="EXPENSE_LARGE_NO_REFERENCE", severity="HIGH", title="مصروف كبير بلا مرجع", message=f"مصروف بقيمة {amount} بدون مرجع واضح.", evidence={**_record_identity(row), "amount": float(amount)}, recommendation="اجعل المرجع أو المرفق إلزامياً للمصاريف الكبيرة.", user_id=uid, model="Expense", record_id=getattr(row, "id", None))
                if _is_blank(desc):
                    self._add_finding(report, code="EXPENSE_NO_DESCRIPTION", severity="MEDIUM", title="مصروف بدون وصف", message="مصروف لا يحتوي وصفًا كافيًا للتدقيق.", evidence={**_record_identity(row), "amount": float(amount)}, recommendation="اجعل وصف المصروف إلزامياً.", user_id=uid, model="Expense", record_id=getattr(row, "id", None))
                key = (str(date_val)[:10], float(amount), str(desc or "").strip().lower(), str(ref or ""))
                seen[key].append(row)
            for key, items in seen.items():
                if len(items) > 1 and key[1] > 0:
                    self._add_finding(report, code="POSSIBLE_DUPLICATE_EXPENSE", severity="HIGH", title="مصاريف مكررة محتملة", message=f"تم العثور على {len(items)} مصروفات متشابهة بنفس التاريخ/المبلغ/الوصف/المرجع.", evidence={"key": key, "expense_ids": [getattr(i, "id", None) for i in items[:10]]}, recommendation="راجع احتمال تكرار المصروف أو إدخاله مرتين.", user_id=_value(items[0], "created_by", "user_id"), model="Expense")
        except Exception as exc:
            report.setdefault("warnings", []).append(f"Expense scan failed: {exc}")

    def _scan_sales_invoice_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        for model_name in ("Sale", "Invoice"):
            Model = _get_model(model_name)
            if Model is None:
                continue
            try:
                q = _within_days_query(Model, days)
                if user_id:
                    user_col = getattr(Model, "seller_id", None) or getattr(Model, "created_by", None) or getattr(Model, "user_id", None)
                    if user_col is not None:
                        q = q.filter(user_col == user_id)
                rows = q.limit(10000).all()
                by_user_cancel = Counter()
                max_discount = _decimal(limits.get("large_discount_percent", 30))
                for row in rows:
                    uid = _value(row, "seller_id", "created_by", "user_id", "cancelled_by")
                    total = _decimal(_value(row, "total_amount", "total", "grand_total"))
                    subtotal = _decimal(_value(row, "subtotal", "sub_total", "before_discount"))
                    discount = _decimal(_value(row, "discount", "discount_total", "discount_amount"))
                    status = str(_value(row, "status", default="") or "").upper()
                    if total < 0:
                        self._add_finding(report, code=f"{model_name.upper()}_NEGATIVE_TOTAL", severity="CRITICAL", title="إجمالي سالب", message=f"{model_name} بإجمالي سالب.", evidence={**_record_identity(row), "total": float(total)}, recommendation="راجع البنود والمرتجعات وطريقة العكس المحاسبي.", user_id=uid, model=model_name, record_id=getattr(row, "id", None))
                    if total == 0 and status not in {"DRAFT", "CANCELLED", "REFUNDED", "RETURNED"}:
                        self._add_finding(report, code=f"{model_name.upper()}_ZERO_TOTAL_ACTIVE", severity="MEDIUM", title="فاتورة/بيع نشط بقيمة صفر", message=f"{model_name} غير ملغى بقيمة صفر.", evidence={**_record_identity(row), "status": status}, recommendation="راجع سبب القيمة الصفرية وهل العملية تدريبية أو خطأ إدخال.", user_id=uid, model=model_name, record_id=getattr(row, "id", None))
                    if subtotal > 0 and discount > 0:
                        pct = (discount / subtotal) * Decimal("100")
                        if pct >= max_discount:
                            self._add_finding(report, code=f"{model_name.upper()}_LARGE_DISCOUNT", severity="HIGH", title="خصم كبير يحتاج موافقة", message=f"خصم {pct:.2f}% يتجاوز حد التنبيه {max_discount}%.", evidence={**_record_identity(row), "subtotal": float(subtotal), "discount": float(discount), "discount_percent": float(pct)}, recommendation="اجعل الخصومات الكبيرة بحاجة موافقة مدير أو سبب موثق.", user_id=uid, model=model_name, record_id=getattr(row, "id", None))
                    if status in {"CANCELLED", "REFUNDED", "RETURNED"}:
                        by_user_cancel[uid] += 1
                max_cancel = _safe_int(limits.get("max_voids_or_cancellations_per_user"), 5)
                for uid, count in by_user_cancel.items():
                    if uid and count >= max_cancel:
                        self._add_finding(report, code=f"{model_name.upper()}_MANY_CANCELS", severity="HIGH", title="إلغاءات أو مرتجعات كثيرة", message=f"المستخدم رقم {uid} لديه {count} عمليات ملغاة/مرتجعة في {model_name}.", evidence={"count": count}, recommendation="راجع أسباب الإلغاء والمرتجعات وربطها بالمخزون والدفعات.", user_id=uid, model=model_name)
            except Exception as exc:
                report.setdefault("warnings", []).append(f"{model_name} scan failed: {exc}")

    def _scan_stock_product_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        StockLevel = _get_model("StockLevel")
        if StockLevel is not None:
            try:
                rows = StockLevel.query.limit(20000).all()
                for row in rows:
                    qty = _decimal(_value(row, "quantity", "qty", "available_qty", "on_hand"))
                    if qty < 0:
                        self._add_finding(report, code="NEGATIVE_STOCK", severity="CRITICAL", title="مخزون سالب", message="كمية مخزون سالبة لمنتج/مستودع.", evidence={**_record_identity(row), "quantity": float(qty), "product_id": _value(row, "product_id"), "warehouse_id": _value(row, "warehouse_id")}, recommendation="راجع آخر حركات بيع/صيانة/تعديل على هذا المنتج والمستودع.", model="StockLevel", record_id=getattr(row, "id", None))
            except Exception as exc:
                report.setdefault("warnings", []).append(f"StockLevel scan failed: {exc}")
        Product = _get_model("Product")
        if Product is not None:
            try:
                rows = Product.query.limit(20000).all()
                for row in rows:
                    sell = _decimal(_value(row, "selling_price", "price", default=0))
                    cost = _decimal(_value(row, "purchase_price", "cost", default=0))
                    if sell > 0 and cost > 0 and sell < cost:
                        self._add_finding(report, code="PRODUCT_SELL_BELOW_COST", severity="MEDIUM", title="سعر بيع أقل من التكلفة", message="منتج سعر بيعه أقل من التكلفة.", evidence={**_record_identity(row), "name": _value(row, "name"), "selling_price": float(sell), "cost": float(cost)}, recommendation="راجع إن كان هذا مقصودًا كعرض أو خطأ في التسعير.", model="Product", record_id=getattr(row, "id", None))
            except Exception as exc:
                report.setdefault("warnings", []).append(f"Product scan failed: {exc}")

    def _scan_permission_risks(self, report: Dict[str, Any], days: int, user_id: Optional[int], limits: Dict[str, Any]) -> None:
        User = _get_model("User")
        if User is None:
            return
        try:
            rows = User.query.filter_by(is_active=True).limit(10000).all() if hasattr(User, "is_active") else User.query.limit(10000).all()
            super_users = []
            for row in rows:
                is_super = bool(
                    getattr(row, "is_system", False)
                    or getattr(row, "is_super_role", False)
                )
                if is_super:
                    super_users.append(row)
            if len(super_users) > 3:
                self._add_finding(report, code="MANY_PRIVILEGED_USERS", severity="HIGH", title="عدد مرتفع من المستخدمين أصحاب الصلاحيات العالية", message=f"يوجد {len(super_users)} مستخدمين بصلاحيات عالية/إدارية.", evidence={"user_ids": [getattr(u, "id", None) for u in super_users[:20]]}, recommendation="راجع مبدأ أقل صلاحية، وافصل صلاحيات البيع/الدفع/الحذف/الإدارة.")
        except Exception as exc:
            report.setdefault("warnings", []).append(f"Permission scan failed: {exc}")

    def _finalize_control_report(self, report: Dict[str, Any]) -> None:
        findings = report.get("findings", [])
        counts = Counter(f.get("severity", "LOW") for f in findings)
        by_code = Counter(f.get("code", "UNKNOWN") for f in findings)
        by_user = Counter(str(f.get("user_id")) for f in findings if f.get("user_id"))
        score = int(report.get("risk_score", 0) or 0)
        if any(f.get("severity") == "CRITICAL" for f in findings) or score >= 40:
            level = "CRITICAL"
            status = "requires_immediate_review"
        elif any(f.get("severity") == "HIGH" for f in findings) or score >= 20:
            level = "HIGH"
            status = "requires_review"
        elif findings:
            level = "MEDIUM"
            status = "watch"
        else:
            level = "LOW"
            status = "clean"
        report["risk_level"] = level
        report["status"] = status
        report["summary"] = {
            "total_findings": len(findings),
            "severity_counts": dict(counts),
            "top_codes": [{"code": code, "count": count} for code, count in by_code.most_common(10)],
            "top_users": [{"user_id": uid, "count": count} for uid, count in by_user.most_common(10)],
        }
        recommendations = []
        if counts.get("CRITICAL"):
            recommendations.append("إيقاف اعتماد الحركات الحرجة مؤقتًا لحين مراجعة بشرية.")
        if by_user:
            recommendations.append("راجع المستخدمين المتكررين في التنبيهات وفعّل مبدأ الفصل بين الصلاحيات.")
        if by_code.get("PAYMENT_LARGE_NO_REFERENCE") or by_code.get("EXPENSE_LARGE_NO_REFERENCE"):
            recommendations.append("اجعل المرجع/المرفق إلزاميًا للحركات المالية الكبيرة.")
        if by_code.get("POSSIBLE_DUPLICATE_PAYMENT") or by_code.get("POSSIBLE_DUPLICATE_EXPENSE"):
            recommendations.append("أضف تحقق تكرار قبل حفظ الدفعات والمصاريف.")
        if by_code.get("MANY_DESTRUCTIVE_ACTIONS") or by_code.get("MANY_ARCHIVES"):
            recommendations.append("اجعل الحذف/الأرشفة/الإلغاء بحاجة موافقة ثانية وسجل سبب إلزامي.")
        if by_code.get("NEGATIVE_STOCK"):
            recommendations.append("امنع المخزون السالب أو اجعله يحتاج موافقة إدارية مع سبب موثق.")
        report["recommendations"] = recommendations or ["استمر بالمراقبة الدورية، ولا توجد مؤشرات رقابية عالية حالياً."]

    def _audit_sale_transaction(self, data: Dict, audit: Dict):
        subtotal = _decimal(data.get("subtotal"))
        discount = _decimal(data.get("discount", data.get("discount_total", 0)))
        vat = _decimal(data.get("vat", data.get("tax_amount", 0)))
        total = _decimal(data.get("total", data.get("total_amount", 0)))
        tax_rate_value = data.get("tax_rate")
        net = subtotal - discount
        if net < 0:
            audit["errors"].append({"code": "INVALID_DISCOUNT", "severity": "HIGH", "message": f"الخصم {discount} أكبر من المجموع الفرعي {subtotal}"})
            net = Decimal("0")
        if tax_rate_value not in (None, ""):
            tax_rate = _decimal(tax_rate_value)
            if tax_rate < 0 or tax_rate > 100:
                audit["errors"].append({"code": "INVALID_TAX_RATE", "severity": "HIGH", "message": f"نسبة الضريبة غير صالحة: {tax_rate}"})
            expected_vat = net * tax_rate / Decimal("100")
            expected_total = net + expected_vat
            if abs(vat - expected_vat) > Decimal("0.01"):
                audit["errors"].append({"code": "VAT_CALC_ERROR", "severity": "HIGH", "message": f"خطأ في حساب VAT: المحسوب {expected_vat:.2f} ≠ المدخل {vat:.2f}", "expected": float(expected_vat), "actual": float(vat), "difference": float(vat - expected_vat)})
            if total > 0 and abs(total - expected_total) > Decimal("0.01"):
                audit["errors"].append({"code": "TOTAL_CALC_ERROR", "severity": "CRITICAL", "message": f"خطأ في الإجمالي: المحسوب {expected_total:.2f} ≠ المدخل {total:.2f}"})
        else:
            audit["warnings"].append({"code": "MISSING_TAX_RATE", "message": "لا يمكن تدقيق الضريبة بدقة بدون tax_rate من الحركة أو الإعدادات"})
        if subtotal == 0:
            audit["warnings"].append({"code": "ZERO_SALE", "message": "فاتورة بقيمة صفر - تحقق من المنطقية"})
        for line in data.get("lines", []) or []:
            quantity = _decimal(line.get("quantity"))
            unit_price = _decimal(line.get("unit_price", line.get("price", 0)))
            if quantity <= 0:
                audit["errors"].append({"code": "INVALID_QUANTITY", "severity": "HIGH", "message": f"كمية غير صالحة: {quantity}"})
            if unit_price < 0:
                audit["errors"].append({"code": "INVALID_UNIT_PRICE", "severity": "HIGH", "message": f"سعر وحدة سالب: {unit_price}"})

    def _audit_payment_transaction(self, data: Dict, audit: Dict):
        amount = _decimal(data.get("amount", data.get("total_amount", 0)))
        direction = str(data.get("direction", "")).upper()
        target_fields = ["customer_id", "supplier_id", "partner_id", "shipment_id", "expense_id", "loan_settlement_id", "sale_id", "invoice_id", "preorder_id", "service_id"]
        selected_targets = [field for field in target_fields if data.get(field)]
        if amount <= 0:
            audit["errors"].append({"code": "INVALID_AMOUNT", "severity": "CRITICAL", "message": "مبلغ الدفعة يجب أن يكون موجباً"})
        if direction not in {"IN", "OUT"}:
            audit["errors"].append({"code": "INVALID_DIRECTION", "severity": "HIGH", "message": "اتجاه الدفعة غير محدد (IN/OUT)"})
        if len(selected_targets) != 1:
            audit["errors"].append({"code": "INVALID_TARGET", "severity": "HIGH", "message": "الدفعة يجب أن ترتبط بجهة واحدة فقط"})

    def _audit_gl_batch(self, data: Dict, audit: Dict):
        entries = data.get("entries", []) or []
        if not entries:
            audit["errors"].append({"code": "EMPTY_BATCH", "severity": "CRITICAL", "message": "قيد فارغ - لا يوجد إدخالات"})
            return
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for entry in entries:
            debit = _entry_amount(entry, "debit", "debit_amount")
            credit = _entry_amount(entry, "credit", "credit_amount")
            total_debit += debit
            total_credit += credit
            if debit > 0 and credit > 0:
                audit["warnings"].append({"code": "BOTH_DEBIT_CREDIT", "message": "إدخال له مدين ودائن معاً - غير منطقي"})
        if abs(total_debit - total_credit) > Decimal("0.01"):
            audit["errors"].append({"code": "UNBALANCED_BATCH", "severity": "CRITICAL", "message": f"قيد غير متوازن: مدين {total_debit:.2f} ≠ دائن {total_credit:.2f}", "debit": float(total_debit), "credit": float(total_credit), "difference": float(total_debit - total_credit)})

    def _audit_stock_adjustment(self, data: Dict, audit: Dict):
        if "new_quantity" in data and _decimal(data.get("new_quantity")) < 0:
            audit["errors"].append({"code": "NEGATIVE_STOCK", "severity": "HIGH", "message": "الكمية الجديدة لا يمكن أن تكون سالبة"})
        adjustment = _decimal(data.get("adjustment", data.get("difference", 0)))
        reason = data.get("reason", "")
        if abs(adjustment) > 100:
            audit["warnings"].append({"code": "LARGE_ADJUSTMENT", "message": f"تعديل كبير في المخزون: {adjustment} - تحقق من السبب"})
        if not reason:
            audit["warnings"].append({"code": "NO_REASON", "message": "تعديل مخزون بدون سبب موثق"})

    def _alert_owner(self, audit: Dict):
        try:
            from AI.engine.ai_realtime_monitor import get_realtime_monitor
            monitor = get_realtime_monitor()
            for error in [e for e in audit["errors"] if e.get("severity") == "CRITICAL"]:
                monitor.add_alert(alert_type="accounting_audit_fail", severity="critical", message=f"تدقيق محاسبي - خطأ حرج: {error['message']}", action="مراجعة فورية ضرورية", data={"transaction_type": audit["transaction_type"], "error_code": error["code"], "details": error})
        except Exception:
            pass

    def _save_audit_log(self):
        try:
            write_json(AUDIT_LOG_FILE, {"audit_log": self.audit_log[-MAX_AUDIT_LOG:], "total_audits": len(self.audit_log), "total_errors": len(self.detected_errors), "last_updated": datetime.now().isoformat()})
            sync_training_manifest(extra_files=[AUDIT_LOG_FILE])
        except Exception:
            pass

    def _save_control_audit_log(self):
        try:
            write_json(CONTROL_AUDIT_LOG_FILE, {"control_audit_log": self.control_audit_log[-MAX_AUDIT_LOG:], "last_updated": _now().isoformat()})
            sync_training_manifest(extra_files=[CONTROL_AUDIT_LOG_FILE])
        except Exception:
            pass

    def get_audit_summary(self) -> Dict:
        if not self.audit_log:
            return {"total_audits": 0, "pass_rate": 0, "common_errors": [], "control_summary": self.get_control_summary()}
        passed = sum(1 for a in self.audit_log if a.get("status") == "pass")
        pass_rate = (passed / len(self.audit_log)) * 100
        error_counts = {}
        for audit in self.audit_log:
            for error in audit.get("errors", []):
                code = error.get("code", "UNKNOWN")
                error_counts[code] = error_counts.get(code, 0) + 1
        common_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        return {"total_audits": len(self.audit_log), "passed": passed, "failed": len(self.audit_log) - passed, "pass_rate": round(pass_rate, 2), "common_errors": [{"code": code, "count": count} for code, count in common_errors], "control_summary": self.get_control_summary()}

    def get_control_summary(self) -> Dict[str, Any]:
        if not self.control_audit_log:
            return {"total_control_audits": 0, "last_risk_level": "N/A", "last_findings": 0}
        last = self.control_audit_log[-1]
        return {"total_control_audits": len(self.control_audit_log), "last_generated_at": last.get("generated_at"), "last_risk_level": last.get("risk_level"), "last_status": last.get("status"), "last_findings": len(last.get("findings", [])), "last_risk_score": last.get("risk_score", 0)}


_accounting_auditor = None


def get_accounting_auditor():
    global _accounting_auditor
    if _accounting_auditor is None:
        _accounting_auditor = AccountingAuditor()
    return _accounting_auditor


__all__ = ["AccountingAuditor", "get_accounting_auditor"]
