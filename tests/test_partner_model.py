from decimal import Decimal
import pytest


class TestPartnerModel:

    def test_create_minimal_partner(self, db_session):
        from models import Partner
        p = Partner(name="test partner", phone_number="0500000300")
        db_session.add(p)
        db_session.commit()
        assert p.id is not None
        assert p.name == "test partner"
        assert p.phone_number == "0500000300"
        assert p.currency == "ILS"
        assert p.share_percentage == 0
        assert p.opening_balance == 0

    def test_partner_email_normalized(self, db_session):
        from models import Partner
        p = Partner(name="Email Partner", phone_number="0500000301", email="  PARTNER@Example.COM  ")
        db_session.add(p)
        db_session.commit()
        assert p.email == "partner@example.com"

    def test_partner_currency_uppercased(self, db_session):
        from models import Partner
        p = Partner(name="USD Partner", phone_number="0500000302", currency="usd")
        db_session.add(p)
        db_session.commit()
        assert p.currency == "USD"

    def test_partner_name_stripped(self, db_session):
        from models import Partner
        p = Partner(name="  Stripped Partner  ", phone_number="0500000303")
        db_session.add(p)
        db_session.commit()
        assert p.name == "Stripped Partner"

    def test_partner_share_percentage_default(self, db_session):
        from models import Partner
        p = Partner(name="Share Default", phone_number="0500000304")
        db_session.add(p)
        db_session.commit()
        assert p.share_percentage == 0

    def test_partner_unique_identity_number(self, db_session):
        from models import Partner
        from sqlalchemy.exc import IntegrityError
        p1 = Partner(name="First ID", phone_number="0500000305", identity_number="PID-001")
        db_session.add(p1)
        db_session.commit()
        p2 = Partner(name="Second ID", phone_number="0500000306", identity_number="PID-001")
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_partner_unique_phone_number(self, db_session):
        from models import Partner
        from sqlalchemy.exc import IntegrityError
        p1 = Partner(name="First Phone", phone_number="0500000307")
        db_session.add(p1)
        db_session.commit()
        p2 = Partner(name="Second Phone", phone_number="0500000307")
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_partner_unique_email_enforced(self, db_session):
        from models import Partner
        from sqlalchemy.exc import IntegrityError
        p1 = Partner(name="First Email", phone_number="0500000308", email="partner_dup@test.com")
        db_session.add(p1)
        db_session.commit()
        p2 = Partner(name="Second Email", phone_number="0500000309", email="partner_dup@test.com")
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_partner_repr(self, db_session):
        from models import Partner
        p = Partner(name="Repr Partner", phone_number="0500000310")
        db_session.add(p)
        db_session.commit()
        assert repr(p) == "<Partner Repr Partner>"

    def test_partner_default_timestamps(self, db_session):
        from models import Partner
        p = Partner(name="Timestamps", phone_number="0500000311")
        db_session.add(p)
        db_session.commit()
        assert p.created_at is not None
        assert p.updated_at is not None

    def test_partner_contact_info_stripped(self, db_session):
        from models import Partner
        p = Partner(name="Contact Info", phone_number="0500000312", contact_info="  Office  ")
        db_session.add(p)
        db_session.commit()
        assert p.contact_info == "Office"

    def test_partner_address_stripped(self, db_session):
        from models import Partner
        p = Partner(name="Address Test", phone_number="0500000313", address="  Ramallah  ")
        db_session.add(p)
        db_session.commit()
        assert p.address == "Ramallah"

    def test_partner_share_percentage_and_balance(self, db_session):
        from models import Partner
        p = Partner(name="Share & Bal", phone_number="0500000314",
                     share_percentage=Decimal("25.00"), current_balance=Decimal("1000.00"))
        db_session.add(p)
        db_session.commit()
        assert float(p.share_percentage) == 25.0
        assert float(p.current_balance) == 1000.0
