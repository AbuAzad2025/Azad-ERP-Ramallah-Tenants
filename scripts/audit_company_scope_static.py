#!/usr/bin/env python3
"""مسح ثابت: استعلامات تشغيلية محتملة بدون نطاق فرع في routes/ (باستثناء security)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "routes"

# نماذج تشغيلية يجب أن تمر عبر company_scope
SCOPED_MODELS = (
    "Payment",
    "Sale",
    "Check",
    "Expense",
    "Customer",
    "Supplier",
    "Partner",
    "ServiceRequest",
    "Shipment",
    "Warehouse",
    "SaleReturn",
)

SCOPE_MARKERS = (
    "filter_payments_query",
    "filter_sales_query",
    "filter_checks_query",
    "filter_expenses_query",
    "filter_customers_query",
    "filter_suppliers_query",
    "filter_partners_query",
    "filter_service_requests_query",
    "filter_shipments_query",
    "filter_warehouses_query",
    "filter_sale_returns_query",
    "filter_branches_query",
    "filter_by_branches",
    "branch_expenses_query",
    "branch_warehouses_query",
    "scoped_payment_query",
    "scoped_check_query",
    "scoped_expense_query",
    "scoped_sale_query",
    "scoped_service_request_query",
    "scoped_shipment_query",
    "accessible_branches_query",
    "assert_customer_access",
    "assert_sale_access",
    "assert_payment_access",
    "assert_supplier_access",
    "assert_partner_access",
    "assert_expense_access",
    "assert_warehouse_access",
    "assert_branch_access",
    "_branch_or_404",
    "apply_gl_branch_filter",
    "gl_entries_base",
    "gl_entries_as_of",
    "payment_ids_in_branches",
    "payment_id_in_accessible_branches",
)

SKIP_FILES = {"security.py", "auth.py", "recurring_invoices.py"}

QUERY_RE = re.compile(
    r"\b(" + "|".join(SCOPED_MODELS) + r")\.query\b"
)

FINDINGS: list[str] = []


def _is_scoped_line(line: str) -> bool:
    if any(m in line for m in SCOPE_MARKERS):
        return True
    # Payment.query داخل filter_*(Payment.query) على سطر سابق — غير مضمون هنا
    return False


def scan_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        FINDINGS.append(f"{path.name}: read error {exc}")
        return
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not QUERY_RE.search(line):
            continue
        context = "\n".join(lines[max(0, i - 5) : i + 1])
        if _is_scoped_line(line) or _is_scoped_line(context):
            continue
        # استثناءات شائعة: تعريف علاقات، تعليقات، OnlinePayment
        if "OnlinePayment" in line or "OnlinePreOrder" in line:
            continue
        rel = path.relative_to(ROOT)
        FINDINGS.append(f"{rel}:{i}: {stripped[:120]}")


def _safe_print(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


def main() -> int:
    _safe_print("=== Company scope static audit ===")
    for py in sorted(ROUTES.glob("*.py")):
        if py.name in SKIP_FILES:
            continue
        scan_file(py)
    if not FINDINGS:
        _safe_print("  OK  no unscoped Model.query patterns detected")
        return 0
    _safe_print(f"  WARN  {len(FINDINGS)} line(s) to review:\n")
    for f in FINDINGS[:80]:
        _safe_print(f"    {f}")
    if len(FINDINGS) > 80:
        _safe_print(f"    ... and {len(FINDINGS) - 80} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
