from decimal import Decimal
import pytest


class TestSupplierModel:

    def test_create_minimal_supplier(self, db_session):
        from models import Supplier
        s = Supplier(name="test supplier", phone="0500000200")
        db_session.add(s)
        db_session.commit()
        assert s.id is not None
        assert s.name == "test supplier"
        assert s.phone == "0500000200"
        assert s.currency == "ILS"
        assert s.is_archived is False
        assert s.opening_balance == 0

    def test_supplier_email_normalized(self, db_session):
        from models import Supplier
        s = Supplier(name="Email Supplier", phone="0500000201", email="  SUPP@Example.COM  ")
        db_session.add(s)
        db_session.commit()
        assert s.email == "supp@example.com"

    def test_supplier_currency_uppercased(self, db_session):
        from models import Supplier
        s = Supplier(name="USD Supplier", phone="0500000202", currency="usd")
        db_session.add(s)
        db_session.commit()
        assert s.currency == "USD"

    def test_supplier_name_stripped(self, db_session):
        from models import Supplier
        s = Supplier(name="  Stripped Supplier  ", phone="0500000203")
        db_session.add(s)
        db_session.commit()
        assert s.name == "Stripped Supplier"

    def test_supplier_contact_stripped(self, db_session):
        from models import Supplier
        s = Supplier(name="Contact Test", phone="0500000204", contact="  John Doe  ")
        db_session.add(s)
        db_session.commit()
        assert s.contact == "John Doe"

    def test_supplier_phone_strips_outer_spaces(self, db_session):
        from models import Supplier
        s = Supplier(name="Phone Strip", phone="  0500 000 205  ")
        db_session.add(s)
        db_session.commit()
        assert s.phone == "0500 000 205"



    def test_supplier_unique_email_enforced(self, db_session):
        from models import Supplier
        from sqlalchemy.exc import IntegrityError
        s1 = Supplier(name="First Email", phone="0500000207", email="supp_dup@test.com")
        db_session.add(s1)
        db_session.commit()
        s2 = Supplier(name="Second Email", phone="0500000208", email="supp_dup@test.com")
        db_session.add(s2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_supplier_unique_identity_number(self, db_session):
        from models import Supplier
        from sqlalchemy.exc import IntegrityError
        s1 = Supplier(name="First ID", phone="0500000209", identity_number="ID-12345")
        db_session.add(s1)
        db_session.commit()
        s2 = Supplier(name="Second ID", phone="0500000210", identity_number="ID-12345")
        db_session.add(s2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_supplier_opening_balance_default(self, db_session):
        from models import Supplier
        s = Supplier(name="Zero Balance", phone="0500000211")
        db_session.add(s)
        db_session.commit()
        assert s.opening_balance == 0

    def test_supplier_repr(self, db_session):
        from models import Supplier
        s = Supplier(name="Repr Supplier", phone="0500000212")
        db_session.add(s)
        db_session.commit()
        assert repr(s) == "<Supplier Repr Supplier>"

    def test_supplier_default_timestamps(self, db_session):
        from models import Supplier
        s = Supplier(name="Timestamps", phone="0500000213")
        db_session.add(s)
        db_session.commit()
        assert s.created_at is not None
        assert s.updated_at is not None
