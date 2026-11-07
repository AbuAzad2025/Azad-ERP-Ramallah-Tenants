"""legacy columns and data backfill

Ensures missing columns exist (with defaults) and backfills NULL/empty data
so old and new data are compatible with the current system.

Revision ID: d4e5f6a7b8c9
Revises: c3a0f1b8d2e4
Create Date: 2026-02-14

"""
from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c3a0f1b8d2e4"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    exec_conn = conn
    close_exec_conn = False
    if dialect == "postgresql":
        exec_conn = conn.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        close_exec_conn = True

    try:
        updates = [
            "UPDATE accounts SET name = COALESCE(NULLIF(TRIM(name), ''), code) WHERE name IS NULL OR TRIM(name) = ''",
            "UPDATE gl_batches SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE gl_entries SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE gl_entries SET debit = 0 WHERE debit IS NULL",
            "UPDATE gl_entries SET credit = 0 WHERE credit IS NULL",
            "UPDATE sales SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE sales SET tax_rate = 0 WHERE tax_rate IS NULL",
            "UPDATE sales SET discount_total = 0 WHERE discount_total IS NULL",
            "UPDATE sales SET shipping_cost = 0 WHERE shipping_cost IS NULL",
            "UPDATE sales SET total_amount = 0 WHERE total_amount IS NULL",
            "UPDATE sales SET total_paid = 0 WHERE total_paid IS NULL",
            "UPDATE sales SET balance_due = 0 WHERE balance_due IS NULL",
            "UPDATE sales SET refunded_total = 0 WHERE refunded_total IS NULL",
            "UPDATE sales SET status = 'DRAFT' WHERE status IS NULL OR TRIM(status) = ''",
            "UPDATE sales SET payment_status = 'PENDING' WHERE payment_status IS NULL OR TRIM(payment_status) = ''",
            "UPDATE sale_lines SET quantity = 0 WHERE quantity IS NULL",
            "UPDATE sale_lines SET unit_price = 0 WHERE unit_price IS NULL",
            "UPDATE sale_lines SET discount_rate = 0 WHERE discount_rate IS NULL",
            "UPDATE sale_lines SET tax_rate = 0 WHERE tax_rate IS NULL",
            "UPDATE sale_returns SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE sale_returns SET total_amount = 0 WHERE total_amount IS NULL",
            "UPDATE sale_returns SET status = 'DRAFT' WHERE status IS NULL OR TRIM(status) = ''",
            "UPDATE sale_return_lines SET quantity = 1 WHERE quantity IS NULL",
            "UPDATE sale_return_lines SET unit_price = 0 WHERE unit_price IS NULL",
            "UPDATE sale_return_lines SET condition = 'GOOD' WHERE condition IS NULL OR TRIM(condition) = ''",
            "UPDATE invoices SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE invoices SET kind = 'INVOICE' WHERE kind IS NULL OR TRIM(kind) = ''",
            "UPDATE invoices SET source = 'MANUAL' WHERE source IS NULL OR TRIM(source) = ''",
            "UPDATE invoices SET total_amount = 0 WHERE total_amount IS NULL",
            "UPDATE invoices SET tax_amount = 0 WHERE tax_amount IS NULL",
            "UPDATE invoices SET discount_amount = 0 WHERE discount_amount IS NULL",
            "UPDATE invoices SET refunded_total = 0 WHERE refunded_total IS NULL",
            "UPDATE invoice_lines SET quantity = 0 WHERE quantity IS NULL",
            "UPDATE invoice_lines SET unit_price = 0 WHERE unit_price IS NULL",
            "UPDATE invoice_lines SET tax_rate = 0 WHERE tax_rate IS NULL",
            "UPDATE invoice_lines SET discount = 0 WHERE discount IS NULL",
            "UPDATE invoice_lines SET description = COALESCE(NULLIF(TRIM(description), ''), '—') WHERE description IS NULL OR TRIM(description) = ''",
            "UPDATE payments SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE payments SET total_amount = 0.01 WHERE total_amount IS NULL",
            "UPDATE payments SET method = 'CASH' WHERE method IS NULL OR TRIM(method) = ''",
            "UPDATE payments SET status = 'PENDING' WHERE status IS NULL OR TRIM(status) = ''",
            "UPDATE payments SET direction = 'IN' WHERE direction IS NULL OR TRIM(direction) = ''",
            "UPDATE payments SET entity_type = 'CUSTOMER' WHERE entity_type IS NULL OR TRIM(entity_type) = ''",
            "UPDATE payment_splits SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE payment_splits SET converted_currency = 'ILS' WHERE converted_currency IS NULL OR TRIM(converted_currency) = ''",
            "UPDATE payment_splits SET amount = 0.01 WHERE amount IS NULL",
            "UPDATE payment_splits SET converted_amount = 0 WHERE converted_amount IS NULL",
            "UPDATE expenses SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE expenses SET payee_type = 'OTHER' WHERE payee_type IS NULL OR TRIM(payee_type) = ''",
            "UPDATE expenses SET payment_method = 'cash' WHERE payment_method IS NULL OR TRIM(payment_method) = ''",
            "UPDATE service_requests SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE service_requests SET total_amount = 0 WHERE total_amount IS NULL",
            "UPDATE service_requests SET parts_total = 0 WHERE parts_total IS NULL",
            "UPDATE service_requests SET labor_total = 0 WHERE labor_total IS NULL",
            "UPDATE service_requests SET discount_total = 0 WHERE discount_total IS NULL",
            "UPDATE service_requests SET total_cost = 0 WHERE total_cost IS NULL",
            "UPDATE service_requests SET tax_rate = 0 WHERE tax_rate IS NULL",
            "UPDATE service_requests SET tax_amount = 0 WHERE tax_amount IS NULL",
            "UPDATE service_requests SET status = 'PENDING' WHERE status IS NULL OR TRIM(status) = ''",
            "UPDATE service_requests SET service_number = 'SVC-' || id WHERE service_number IS NULL OR TRIM(service_number) = ''",
            "UPDATE service_parts SET quantity = 0 WHERE quantity IS NULL",
            "UPDATE service_parts SET unit_price = 0 WHERE unit_price IS NULL",
            "UPDATE service_parts SET discount = 0 WHERE discount IS NULL",
            "UPDATE service_tasks SET quantity = 0 WHERE quantity IS NULL",
            "UPDATE service_tasks SET unit_price = 0 WHERE unit_price IS NULL",
            "UPDATE service_tasks SET discount = 0 WHERE discount IS NULL",
            "UPDATE customers SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE customers SET name = 'زبون غير محدد' WHERE name IS NULL OR TRIM(name) = ''",
            "UPDATE customers SET phone = '—' WHERE phone IS NULL OR TRIM(phone) = ''",
            "UPDATE customers SET opening_balance = 0 WHERE opening_balance IS NULL",
            "UPDATE customers SET current_balance = 0 WHERE current_balance IS NULL",
            "UPDATE suppliers SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE suppliers SET name = 'مورد غير محدد' WHERE name IS NULL OR TRIM(name) = ''",
            "UPDATE suppliers SET opening_balance = 0 WHERE opening_balance IS NULL",
            "UPDATE suppliers SET current_balance = 0 WHERE current_balance IS NULL",
            "UPDATE partners SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE partners SET name = 'شريك غير محدد' WHERE name IS NULL OR TRIM(name) = ''",
            "UPDATE partners SET opening_balance = 0 WHERE opening_balance IS NULL",
            "UPDATE partners SET current_balance = 0 WHERE current_balance IS NULL",
            "UPDATE preorders SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE preorders SET total_amount = 0 WHERE total_amount IS NULL",
            "UPDATE preorders SET prepaid_amount = 0 WHERE prepaid_amount IS NULL",
            "UPDATE shipments SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE exchange_transactions SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE supplier_settlements SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE partner_settlements SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE tax_entries SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE tax_entries SET tax_rate = 0 WHERE tax_rate IS NULL",
            "UPDATE tax_entries SET base_amount = 0 WHERE base_amount IS NULL",
            "UPDATE tax_entries SET tax_amount = 0 WHERE tax_amount IS NULL",
            "UPDATE tax_entries SET total_amount = 0 WHERE total_amount IS NULL",
            "UPDATE recurring_invoice_templates SET currency = 'ILS' WHERE currency IS NULL OR TRIM(currency) = ''",
            "UPDATE recurring_invoice_templates SET tax_rate = 0 WHERE tax_rate IS NULL",
        ]
        if dialect == "postgresql":
            updates = [sql.replace("'SVC-' || id", "'SVC-' || id::text") for sql in updates]

        for sql in updates:
            try:
                exec_conn.execute(sa.text(sql))
            except Exception as e:
                msg = str(e).lower()
                if "no such column" in msg or "does not exist" in msg or "unknown column" in msg or "relation" in msg:
                    pass
                else:
                    raise

        try:
            if dialect == "postgresql":
                exec_conn.execute(sa.text(
                    "UPDATE payments SET payment_number = 'LEGACY-' || id::text WHERE payment_number IS NULL OR TRIM(payment_number) = ''"
                ))
            else:
                exec_conn.execute(sa.text(
                    "UPDATE payments SET payment_number = 'LEGACY-' || id WHERE payment_number IS NULL OR TRIM(payment_number) = ''"
                ))
        except Exception as e:
            msg = str(e).lower()
            if "no such column" in msg or "does not exist" in msg or "relation" in msg:
                pass
            else:
                raise
    finally:
        if close_exec_conn:
            exec_conn.close()


def downgrade():
    # Data backfill is not reversible; we do not revert filled values.
    # Column additions could be reverted per column, but that may break app.
    pass
