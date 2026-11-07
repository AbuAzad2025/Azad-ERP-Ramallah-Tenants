"""اعتماد مستندات — workflow خفيف."""
from __future__ import annotations

from datetime import datetime, timezone

from extensions import db
from models import DocumentApproval


def request_approval(document_type: str, document_id: int, user_id: int, level: int = 1) -> DocumentApproval:
    existing = DocumentApproval.query.filter_by(
        document_type=document_type.upper(),
        document_id=document_id,
        level_no=level,
        status="PENDING",
    ).first()
    if existing:
        return existing
    row = DocumentApproval(
        document_type=document_type.upper(),
        document_id=document_id,
        level_no=level,
        status="PENDING",
        requested_by_id=user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def approve_document(document_type: str, document_id: int, approver_id: int, level: int = 1) -> bool:
    row = DocumentApproval.query.filter_by(
        document_type=document_type.upper(),
        document_id=document_id,
        level_no=level,
        status="PENDING",
    ).first()
    if not row:
        return False
    row.status = "APPROVED"
    row.approved_by_id = approver_id
    row.approved_at = datetime.now(timezone.utc)
    db.session.commit()
    return True


def is_approved(document_type: str, document_id: int, level: int = 1) -> bool:
    return (
        DocumentApproval.query.filter_by(
            document_type=document_type.upper(),
            document_id=document_id,
            level_no=level,
            status="APPROVED",
        ).first()
        is not None
    )
