#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""استعادة نسخة إنتاج + تهجير + تحسينات ما بعد الاستعادة."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore production backup and upgrade")
    parser.add_argument(
        "--backup",
        default=os.path.join(ROOT, "instance", "backups", "backup_20260523_055520.dump"),
        help="Path to .dump backup file",
    )
    parser.add_argument("--skip-restore", action="store_true")
    parser.add_argument("--skip-upgrade", action="store_true")
    parser.add_argument("--skip-optimize", action="store_true")
    parser.add_argument("--skip-integrity", action="store_true")
    args = parser.parse_args()

    backup_path = os.path.abspath(args.backup)
    if not args.skip_restore and not os.path.isfile(backup_path):
        print(f"ERROR: backup not found: {backup_path}")
        return 1

    from app import create_app
    from extensions import db, restore_database, perform_vacuum_optimize

    app = create_app()
    with app.app_context():
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        print("Target DB:", uri.split("@")[-1] if "@" in uri else uri)

        if not args.skip_restore:
            print(f"\n=== 1) Restore from {backup_path} ===")
            ok, msg = restore_database(app, backup_path)
            print(msg)
            if not ok:
                return 2
            try:
                db.session.remove()
                db.engine.dispose()
            except Exception:
                pass

        if not args.skip_upgrade:
            print("\n=== 2) Alembic upgrade (head) ===")
            from flask_migrate import upgrade as migrate_upgrade

            migrate_upgrade()
            print("Migrations applied.")

        if not args.skip_integrity:
            print("\n=== 3) Accounting integrity repair ===")
            import subprocess

            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts", "fix_accounting_integrity.py"), "--apply"],
                cwd=ROOT,
            )
            if proc.returncode != 0:
                print("WARNING: integrity script returned", proc.returncode)

        import click
        from cli import link_missing_counterparties, optimize_db, sync_balances

        if not args.skip_optimize:
            print("\n=== 4) DB optimize (indexes + VACUUM) ===")
            with click.Context(click.Command("optimize-db")):
                optimize_db.callback(dry_run=False)
            perform_vacuum_optimize(app)

        print("\n=== 5) Link missing counterparties ===")
        with click.Context(click.Command("link-missing-counterparties")):
            link_missing_counterparties.callback()

        print("\n=== 5b) Sync entity balances ===")
        with click.Context(click.Command("sync-balances")):
            sync_balances.callback(
                entity="all", limit=None, dry_run=False, include_archived=False, batch_size=50
            )

        print("\n=== 6) Verify counts ===")
        import subprocess

        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify_local_db.py")], cwd=ROOT)

        print("\n=== 7) ERP readiness ===")
        from utils.erp_readiness import run_erp_readiness

        report = run_erp_readiness(app)
        print("Readiness score:", report.get("overall_score_pct", report))

        print("\n=== 8) Comprehensive audit ===")
        from utils.comprehensive_audit import run_comprehensive_audit, format_audit_report_text

        audit = run_comprehensive_audit(app)
        print(format_audit_report_text(audit)[:2000])

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
