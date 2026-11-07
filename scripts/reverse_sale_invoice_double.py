"""عكس الازدواج التاريخي: قيود INVOICE المختلسة لفاتورات مرتبطة بمبيعة.
لا يُنفَّذ تلقائياً — للمراجعة اليدوية فقط بعد تصدير تقرير.
Usage: python scripts/reverse_sale_invoice_double.py --dry-run
"""
import sys
sys.path.insert(0, '.')
import os
os.environ['DATABASE_URL'] = os.environ.get('DATABASE_URL', 'postgresql://postgres@localhost:5432/azad_erp')
from datetime import datetime, timezone
from sqlalchemy import text as sa_text

def main(dry=True):
    from app import create_app
    from extensions import db
    app = create_app()
    with app.app_context():
        rows = db.session.execute(
            sa_text(
                "SELECT ib.id AS ib_id, ib.code AS ib_code, i.id AS inv_id, i.invoice_number "
                "FROM gl_batches ib JOIN invoices i ON i.id = ib.source_id "
                "WHERE ib.source_type='INVOICE' AND ib.status='POSTED' AND i.sale_id IS NOT NULL "
                "ORDER BY i.id"
            )
        ).fetchall()
        print(f"found {len(rows)} double batches (INVOICE linked to sale)")
        for r in rows:
            print(f" invoice {r[2]} batch {r[0]} code {r[1]}")
        if dry:
            print("DRY-RUN: لم يتم تغيير أي شيء. للتنفيذ أزل --dry-run بعد مراجعة مالية يدوية.")
            return
        from models import _gl_upsert_batch_and_entries, GL_ACCOUNTS
        conn = db.session.connection()
        for r in rows:
            inv_id = int(r[2])
            # idempotency: skip if already reversed
            already = db.session.execute(
                sa_text("SELECT 1 FROM gl_batches WHERE source_type='INVOICE_REVERSAL_HIST' AND source_id=:i AND status='POSTED' LIMIT 1"),
                {"i": inv_id},
            ).first()
            if already:
                print(f"  skip invoice {inv_id} (already reversed)")
                continue
            inv = db.session.execute(sa_text("SELECT invoice_number, total_amount, currency, customer_id, invoice_date FROM invoices WHERE id=:i"), {"i": inv_id}).first()
            if not inv:
                continue
            amount = float(inv.total_amount or 0)
            if amount <= 0:
                continue
            ar_account = GL_ACCOUNTS.get("AR", "1100_AR")
            revenue_account = GL_ACCOUNTS.get("REV", "4000_SALES")
            entries = [(revenue_account, amount, 0.0), (ar_account, 0.0, amount)]
            _gl_upsert_batch_and_entries(conn, source_type="INVOICE_REVERSAL_HIST", source_id=inv_id, purpose="REVERSAL",
                currency="ILS", memo=f"Correction: reverse double INVOICE for sale-linked invoice #{inv_id} ({inv.invoice_number})",
                entries=entries, ref=f"REV-HIST-INV-{inv_id}", entity_type="CUSTOMER", entity_id=inv.customer_id,
                posted_at=inv.invoice_date or datetime.now(timezone.utc))
        db.session.commit()
        print("done: historical reversals posted")

if __name__ == '__main__':
    main(dry='--dry-run' in sys.argv)
