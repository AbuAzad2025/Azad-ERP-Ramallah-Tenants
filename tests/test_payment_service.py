from datetime import datetime, timezone
from decimal import Decimal
import pytest


def _payment_kwargs(**overrides):
    kwargs = dict(
        payment_number="PMT-TEST-000001",
        total_amount=Decimal("100.00"),
        method="cash",
        status="PENDING",
        direction="IN",
        entity_type="CUSTOMER",
        customer_id=1,
        currency="ILS",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    kwargs.update(overrides)
    return kwargs


class TestPaymentModel:

    def test_create_minimal_payment(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs())
        db_session.add(p)
        db_session.commit()
        assert p.id is not None
        assert p.payment_number == "PMT-TEST-000001"
        assert p.total_amount == Decimal("100.00")
        assert p.status == "PENDING"
        assert p.direction == "IN"
        assert p.entity_type == "CUSTOMER"
        assert p.customer_id == 1

    def test_payment_total_positive_constraint(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(total_amount=Decimal("0.00")))
        db_session.add(p)
        with pytest.raises(ValueError, match="يجب أن يكون أكبر من صفر"):
            db_session.commit()

    def test_payment_unique_number(self, db_session):
        from models import Payment
        from sqlalchemy.exc import IntegrityError
        p1 = Payment(**_payment_kwargs())
        db_session.add(p1)
        db_session.commit()
        p2 = Payment(**_payment_kwargs(payment_number="PMT-TEST-000001"))
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_payment_requires_total_amount(self, db_session):
        from models import Payment
        p = Payment(payment_number="PMT-NO-AMOUNT")
        db_session.add(p)
        with pytest.raises(ValueError, match="يجب أن يكون أكبر من صفر"):
            db_session.commit()

    def test_payment_with_receipt_and_notes(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(
            receipt_number="RCP-000001",
            notes="test receipt",
        ))
        db_session.add(p)
        db_session.commit()
        assert p.receipt_number == "RCP-000001"
        assert p.notes == "test receipt"

    def test_payment_default_timestamps(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs())
        db_session.add(p)
        db_session.commit()
        assert p.created_at is not None
        assert p.updated_at is not None

    def test_payment_customer_relationship(self, db_session):
        from models import Payment, Customer
        p = Payment(**_payment_kwargs())
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)
        cust = db_session.get(Customer, 1)
        assert p.customer is not None
        assert p.customer.name == cust.name

    def test_payment_supplier_direction_out(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(
            payment_number="PMT-SUP-OUT-001",
            direction="OUT",
            entity_type="SUPPLIER",
            customer_id=None,
            supplier_id=1,
            total_amount=Decimal("50.00"),
        ))
        db_session.add(p)
        db_session.commit()
        assert p.direction == "OUT"
        assert p.entity_type == "SUPPLIER"
        assert p.supplier_id == 1
        assert p.customer_id is None

    def test_payment_partner_entity(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(
            payment_number="PMT-PARTNER-001",
            entity_type="PARTNER",
            customer_id=None,
            partner_id=1,
            total_amount=Decimal("75.00"),
        ))
        db_session.add(p)
        db_session.commit()
        assert p.entity_type == "PARTNER"
        assert p.partner_id == 1

    def test_payment_idempotency_key_unique(self, db_session):
        from models import Payment
        from sqlalchemy.exc import IntegrityError
        key = "idem-test-001"
        p1 = Payment(**_payment_kwargs(
            payment_number="PMT-IDEM-001",
            idempotency_key=key,
        ))
        db_session.add(p1)
        db_session.commit()
        p2 = Payment(**_payment_kwargs(
            payment_number="PMT-IDEM-002",
            idempotency_key=key,
        ))
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_payment_fx_fields(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(
            payment_number="PMT-FX-001",
            currency="USD",
            fx_rate_used=Decimal("3.500000"),
            fx_rate_source="manual",
        ))
        db_session.add(p)
        db_session.commit()
        assert p.currency == "USD"
        assert p.fx_rate_used == Decimal("3.500000")
        assert p.fx_rate_source == "manual"

    def test_payment_cash_method_default(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(method="cash"))
        db_session.add(p)
        db_session.commit()
        assert p.method == "cash"

    def test_payment_bank_transfer_details(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(
            payment_number="PMT-BANK-001",
            method="bank",
            bank_transfer_ref="TRF-98765",
        ))
        db_session.add(p)
        db_session.commit()
        assert p.method == "bank"
        assert p.bank_transfer_ref == "TRF-98765"

    def test_payment_cheque_details(self, db_session):
        from models import Payment
        p = Payment(**_payment_kwargs(
            payment_number="PMT-CHEQUE-001",
            method="cheque",
            check_number="CHK-0001",
            check_bank="Bank of Test",
            check_due_date=datetime(2026, 6, 30, tzinfo=timezone.utc),
        ))
        db_session.add(p)
        db_session.commit()
        assert p.method == "cheque"
        assert p.check_number == "CHK-0001"
        assert p.check_bank == "Bank of Test"
