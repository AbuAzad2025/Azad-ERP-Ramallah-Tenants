#!/usr/bin/env python3
"""تطبيق scoped_check_query / scoped_payment_query على routes/checks.py (مرة واحدة)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "routes" / "checks.py"
text = path.read_text(encoding="utf-8")

MARKERS = (
    "filter_checks_query",
    "filter_payments_query",
    "scoped_check_query",
    "scoped_payment_query",
)

IMPORT_BLOCK = (
    "from utils.company_scope import scoped_check_query, scoped_payment_query\n"
)

if "scoped_check_query" not in text.split("checks_bp = Blueprint", 1)[0]:
    text = text.replace(
        "checks_bp = Blueprint('checks', __name__, url_prefix='/checks')\n",
        "checks_bp = Blueprint('checks', __name__, url_prefix='/checks')\n\n"
        + IMPORT_BLOCK,
        1,
    )

out_lines = []
for line in text.splitlines():
    if any(m in line for m in MARKERS):
        out_lines.append(line)
        continue
    if "Check.query" in line:
        line = line.replace("Check.query", "scoped_check_query()")
    if "Payment.query" in line:
        line = line.replace("Payment.query", "scoped_payment_query()")
    out_lines.append(line)

new_text = "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")
# إزالة filter_checks_query(scoped_check_query()) المزدوج
new_text = new_text.replace(
    "filter_checks_query(scoped_check_query())",
    "scoped_check_query()",
)
new_text = new_text.replace(
    "filter_checks_query(\n                scoped_check_query()",
    "scoped_check_query(",
)
path.write_text(new_text, encoding="utf-8")
print("checks.py updated")
