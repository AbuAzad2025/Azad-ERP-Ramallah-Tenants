"""AI Accounting Auditor."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict

from AI.engine.ai_storage import read_json, sync_training_manifest, write_json

AUDIT_LOG_FILE = "accounting_audit_log.json"
MAX_AUDIT_LOG = 500


class AccountingAuditor:
    def __init__(self):
        self.audit_log = []
        self.detected_errors = []
        self.suspicious_transactions = []
        self._load_audit_log()

    def _load_audit_log(self):
        data = read_json(AUDIT_LOG_FILE, {})
        if isinstance(data, dict):
            log = data.get("audit_log", [])
            self.audit_log = log[-MAX_AUDIT_LOG:] if isinstance(log, list) else []
            self.detected_errors = [audit for audit in self.audit_log if audit.get("status") == "fail"]

    def audit_transaction(self, transaction_type: str, data: Dict) -> Dict:
        audit = {
            "transaction_type": transaction_type,
            "timestamp": datetime.now().isoformat(),
            "status": "pass",
            "errors": [],
            "warnings": [],
            "recommendations": [],
        }

        if transaction_type == "sale":
            self._audit_sale_transaction(data, audit)
        elif transaction_type == "payment":
            self._audit_payment_transaction(data, audit)
        elif transaction_type == "gl_batch":
            self._audit_gl_batch(data, audit)
        elif transaction_type == "stock_adjustment":
            self._audit_stock_adjustment(data, audit)

        if audit["errors"]:
            audit["status"] = "fail"
            self.detected_errors.append(audit)
            self._alert_owner(audit)

        self.audit_log.append(audit)
        self.audit_log = self.audit_log[-MAX_AUDIT_LOG:]
        self.detected_errors = self.detected_errors[-MAX_AUDIT_LOG:]
        self._save_audit_log()
        return audit

    def _audit_sale_transaction(self, data: Dict, audit: Dict):
        subtotal = Decimal(str(data.get("subtotal", 0)))
        discount = Decimal(str(data.get("discount", 0)))
        vat = Decimal(str(data.get("vat", 0)))
        total = Decimal(str(data.get("total", 0)))

        net = subtotal - discount
        expected_vat = net * Decimal("0.16")
        expected_total = net + expected_vat

        if abs(vat - expected_vat) > Decimal("0.01"):
            audit["errors"].append({"code": "VAT_CALC_ERROR", "severity": "HIGH", "message": f"خطأ في حساب VAT: المحسوب {expected_vat:.2f} ≠ المدخل {vat:.2f}", "expected": float(expected_vat), "actual": float(vat), "difference": float(vat - expected_vat)})

        if abs(total - expected_total) > Decimal("0.01"):
            audit["errors"].append({"code": "TOTAL_CALC_ERROR", "severity": "CRITICAL", "message": f"خطأ في الإجمالي: المحسوب {expected_total:.2f} ≠ المدخل {total:.2f}"})

        if subtotal == 0:
            audit["warnings"].append({"code": "ZERO_SALE", "message": "فاتورة بقيمة صفر - تحقق من المنطقية"})

        if discount > subtotal:
            audit["errors"].append({"code": "INVALID_DISCOUNT", "severity": "HIGH", "message": f"الخصم {discount} أكبر من المجموع الفرعي {subtotal}"})

        for line in data.get("lines", []) or []:
            quantity = Decimal(str(line.get("quantity", 0)))
            if quantity <= 0:
                audit["errors"].append({"code": "INVALID_QUANTITY", "severity": "HIGH", "message": f"كمية غير صالحة: {quantity}"})

    def _audit_payment_transaction(self, data: Dict, audit: Dict):
        amount = Decimal(str(data.get("amount", 0)))
        direction = data.get("direction", "")
        entity_type = data.get("entity_type", "")
        entity_id = data.get("entity_id")

        if amount <= 0:
            audit["errors"].append({"code": "INVALID_AMOUNT", "severity": "CRITICAL", "message": "مبلغ الدفعة يجب أن يكون موجباً"})
        if not direction or direction not in ["IN", "OUT"]:
            audit["errors"].append({"code": "INVALID_DIRECTION", "severity": "HIGH", "message": "اتجاه الدفعة غير محدد (IN/OUT)"})
        if not entity_type or not entity_id:
            audit["errors"].append({"code": "MISSING_ENTITY", "severity": "HIGH", "message": "دفعة بدون جهة مرتبطة"})

    def _audit_gl_batch(self, data: Dict, audit: Dict):
        entries = data.get("entries", []) or []
        if not entries:
            audit["errors"].append({"code": "EMPTY_BATCH", "severity": "CRITICAL", "message": "قيد فارغ - لا يوجد إدخالات"})
            return

        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for entry in entries:
            debit = Decimal(str(entry.get("debit", 0)))
            credit = Decimal(str(entry.get("credit", 0)))
            total_debit += debit
            total_credit += credit
            if debit > 0 and credit > 0:
                audit["warnings"].append({"code": "BOTH_DEBIT_CREDIT", "message": "إدخال له مدين ودائن معاً - غير منطقي"})

        if abs(total_debit - total_credit) > Decimal("0.01"):
            audit["errors"].append({"code": "UNBALANCED_BATCH", "severity": "CRITICAL", "message": f"قيد غير متوازن: مدين {total_debit:.2f} ≠ دائن {total_credit:.2f}", "debit": float(total_debit), "credit": float(total_credit), "difference": float(total_debit - total_credit)})

    def _audit_stock_adjustment(self, data: Dict, audit: Dict):
        adjustment = Decimal(str(data.get("adjustment", 0)))
        reason = data.get("reason", "")
        if abs(adjustment) > 100:
            audit["warnings"].append({"code": "LARGE_ADJUSTMENT", "message": f"تعديل كبير في المخزون: {adjustment} - تحقق من السبب"})
        if not reason:
            audit["warnings"].append({"code": "NO_REASON", "message": "تعديل مخزون بدون سبب موثق"})

    def _alert_owner(self, audit: Dict):
        try:
            from AI.engine.ai_realtime_monitor import get_realtime_monitor

            monitor = get_realtime_monitor()
            critical_errors = [e for e in audit["errors"] if e.get("severity") == "CRITICAL"]
            for error in critical_errors:
                monitor.add_alert(
                    alert_type="accounting_audit_fail",
                    severity="critical",
                    message=f"تدقيق محاسبي - خطأ حرج: {error['message']}",
                    action="مراجعة فورية ضرورية",
                    data={"transaction_type": audit["transaction_type"], "error_code": error["code"], "details": error},
                )
        except Exception as exc:
            print(f"Alert error: {exc}")

    def _save_audit_log(self):
        try:
            write_json(
                AUDIT_LOG_FILE,
                {
                    "audit_log": self.audit_log[-MAX_AUDIT_LOG:],
                    "total_audits": len(self.audit_log),
                    "total_errors": len(self.detected_errors),
                    "last_updated": datetime.now().isoformat(),
                },
            )
            sync_training_manifest(extra_files=[AUDIT_LOG_FILE])
        except Exception:
            pass

    def get_audit_summary(self) -> Dict:
        if not self.audit_log:
            return {"total_audits": 0, "pass_rate": 0, "common_errors": []}
        passed = sum(1 for a in self.audit_log if a.get("status") == "pass")
        pass_rate = (passed / len(self.audit_log)) * 100
        error_counts = {}
        for audit in self.audit_log:
            for error in audit.get("errors", []):
                code = error.get("code", "UNKNOWN")
                error_counts[code] = error_counts.get(code, 0) + 1
        common_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        return {"total_audits": len(self.audit_log), "passed": passed, "failed": len(self.audit_log) - passed, "pass_rate": round(pass_rate, 2), "common_errors": [{"code": code, "count": count} for code, count in common_errors]}


_accounting_auditor = None


def get_accounting_auditor():
    global _accounting_auditor
    if _accounting_auditor is None:
        _accounting_auditor = AccountingAuditor()
    return _accounting_auditor


__all__ = ["AccountingAuditor", "get_accounting_auditor"]
