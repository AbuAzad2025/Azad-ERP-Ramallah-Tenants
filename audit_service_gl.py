"""Audit completed service requests missing GL revenue postings."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def audit_service_gl_section(app) -> dict[str, Any]:
    """Structured audit section for comprehensive_audit integration."""
    from models import GLBatch, Payment, ServiceRequest

    issues: list[dict[str, Any]] = []
    missing_ids: list[int] = []

    with app.app_context():
        completed_services = ServiceRequest.query.filter(
            ServiceRequest.status.in_(["COMPLETED", "DELIVERED"])
        ).all()
        completed_count = len(completed_services)

        for svc in completed_services:
            gl_batch = GLBatch.query.filter(
                GLBatch.source_type == "SERVICE",
                GLBatch.source_id == svc.id,
                GLBatch.status == "POSTED",
            ).first()
            if gl_batch:
                continue
            missing_ids.append(svc.id)
            customer_name = svc.customer.name if svc.customer else "Unknown"
            issues.append(
                {
                    "level": "warning",
                    "category": "service_gl",
                    "msg": (
                        f"Service {svc.id} ({svc.service_number}) completed without GL: "
                        f"{customer_name}, amount={svc.total_amount}"
                    ),
                }
            )

    return {
        "completed_count": completed_count,
        "missing_gl_count": len(missing_ids),
        "missing_service_ids": missing_ids,
        "issues": issues,
    }


def audit_service_gl() -> list[int]:
    """Interactive CLI audit; returns service IDs missing GL batches."""
    os.chdir(ROOT)
    from app import create_app

    app = create_app()
    section = audit_service_gl_section(app)
    missing_ids = section["missing_service_ids"]

    print("\n=======================================================")
    print("          AUDIT: COMPLETED SERVICES GL SYNC           ")
    print("=======================================================")
    print(f"Completed services checked: {section.get('completed_count', '?')}")

    if not missing_ids:
        print("All completed services have GL entries.")
    else:
        print(f"Found {len(missing_ids)} completed services WITHOUT GL entries.")
        for iss in section.get("issues", []):
            print(f" - {iss.get('msg', '')}")

    return missing_ids


if __name__ == "__main__":
    audit_service_gl()
