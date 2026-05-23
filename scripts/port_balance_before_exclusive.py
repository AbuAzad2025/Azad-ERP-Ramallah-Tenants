"""Add before_exclusive filters to all balance component queries."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "utils" / "balance_calculator.py"
text = p.read_text(encoding="utf-8")

DATE_COLS = [
    ("Sale.", "Sale.sale_date"),
    ("SaleReturn.", "SaleReturn.created_at"),
    ("Invoice.", "Invoice.invoice_date"),
    ("OnlinePreOrder.", "OnlinePreOrder.created_at"),
    ("Payment.", "Payment.payment_date"),
    ("Check.", "Check.check_date"),
    ("PreOrder.", "PreOrder.preorder_date"),
    ("Expense.", "Expense.date"),
    ("ServiceRequest.", "ServiceRequest.received_at"),
]

start = text.index("def calculate_customer_balance_components")
end = text.index("def build_customer_balance_view")
func = text[start:end]
lines = func.splitlines(keepends=True)
new_lines: list[str] = []
i = 0
while i < len(lines):
    line = lines[i]
    if ".filter(" not in line:
        new_lines.append(line)
        i += 1
        continue
    j = i
    block: list[str] = []
    while j < len(lines):
        block.append(lines[j])
        if re.search(r"\)\.(scalar|all|first|one|count)\(", lines[j]):
            break
        j += 1
    blk = "".join(block)
    if "before_exclusive" not in blk:
        col = None
        for prefix, date_col in DATE_COLS:
            if prefix in blk:
                col = date_col
                break
        if col:
            indent = "            "
            ins = "%s*_before_exclusive_filters(before_exclusive, %s),\n" % (indent, col)
            # insert before terminal ).scalar|all|...
            for k in range(len(block) - 1, -1, -1):
                if re.search(r"\)\.(scalar|all|first|one|count)\(", block[k]):
                    block.insert(k, ins)
                    break
    new_lines.extend(block)
    i = j + 1

text = text[:start] + "".join(new_lines) + text[end:]
p.write_text(text, encoding="utf-8")
n = text.count("_before_exclusive_filters(before_exclusive")
print("Updated", p, "filters:", n)
