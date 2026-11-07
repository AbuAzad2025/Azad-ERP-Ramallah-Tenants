from datetime import datetime, timezone
from decimal import Decimal
import pytest


class TestCustomerModel:

    def test_create_minimal_customer(self, db_session):
        from models import Customer
        c = Customer(name="test customer", phone="0500000100")
        db_session.add(c)
        db_session.commit()
        assert c.id is not None
        assert c.name == "test customer"
        assert c.phone == "0500000100"
        assert c.category == "عادي"
        assert c.currency == "ILS"
        assert c.is_active is True
        assert c.is_online is False
        assert c.is_archived is False
        assert isinstance(c.created_at, datetime)
        assert isinstance(c.updated_at, datetime)

    def test_customer_email_normalized(self, db_session):
        from models import Customer
        c = Customer(name="Email Test", phone="0500000101", email="  Test@Example.COM  ")
        db_session.add(c)
        db_session.commit()
        assert c.email == "test@example.com"

    def test_customer_empty_email_becomes_none(self, db_session):
        from models import Customer
        c = Customer(name="No Email", phone="0500000102", email="   ")
        db_session.add(c)
        db_session.commit()
        assert c.email is None

    def test_customer_phone_strips_spaces(self, db_session):
        from models import Customer
        c = Customer(name="Phone Test", phone="  0500 000 103  ")
        db_session.add(c)
        db_session.commit()
        assert c.phone == "0500000103"

    def test_customer_phone_with_plus(self, db_session):
        from models import Customer
        c = Customer(name="Plus Phone", phone="+972 50 000 0104")
        db_session.add(c)
        db_session.commit()
        assert c.phone == "+972500000104"

    def test_customer_invalid_phone_too_short(self, db_session):
        from models import Customer
        with pytest.raises(ValueError, match="رقم الهاتف"):
            Customer(name="Short Phone", phone="123")

    def test_customer_category_defaults(self, db_session):
        from models import Customer
        c = Customer(name="Category Test", phone="0500000105", category="  ")
        db_session.add(c)
        db_session.commit()
        assert c.category == "عادي"

    def test_customer_category_invalid_falls_back(self, db_session):
        from models import Customer
        c = Customer(name="Bad Category", phone="0500000106", category="VIP")
        db_session.add(c)
        db_session.commit()
        assert c.category == "عادي"

    def test_customer_category_gold(self, db_session):
        from models import Customer
        c = Customer(name="Gold Customer", phone="0500000107", category="ذهبي")
        db_session.add(c)
        db_session.commit()
        assert c.category == "ذهبي"

    def test_customer_currency_uppercased(self, db_session):
        from models import Customer
        c = Customer(name="USD Customer", phone="0500000108", currency="usd")
        db_session.add(c)
        db_session.commit()
        assert c.currency == "USD"

    def test_customer_unique_phone_enforced(self, db_session):
        from models import Customer
        from sqlalchemy.exc import IntegrityError
        c1 = Customer(name="First", phone="0500000109")
        db_session.add(c1)
        db_session.commit()
        c2 = Customer(name="Second", phone="0500000109")
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_customer_unique_email_enforced(self, db_session):
        from models import Customer
        from sqlalchemy.exc import IntegrityError
        c1 = Customer(name="First Email", phone="0500000110", email="dup@test.com")
        db_session.add(c1)
        db_session.commit()
        c2 = Customer(name="Second Email", phone="0500000111", email="dup@test.com")
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_customer_discount_rate_default(self, db_session):
        from models import Customer
        c = Customer(name="Discount Test", phone="0500000112")
        db_session.add(c)
        db_session.commit()
        assert c.discount_rate == 0

    def test_customer_discount_rate_out_of_range(self, db_session):
        from models import Customer
        with pytest.raises(ValueError, match="نسبة الخصم"):
            Customer(name="Bad Discount", phone="0500000113", discount_rate=Decimal("150.00"))

    def test_customer_credit_limit_default(self, db_session):
        from models import Customer
        c = Customer(name="Credit Test", phone="0500000114")
        db_session.add(c)
        db_session.commit()
        assert c.credit_limit == 0

    def test_customer_negative_credit_limit_raises(self, db_session):
        from models import Customer
        with pytest.raises(ValueError, match="حد الائتمان"):
            Customer(name="Neg Credit", phone="0500000115", credit_limit=Decimal("-100.00"))

    def test_customer_balance_hybrid_property(self, db_session):
        from models import Customer
        c = Customer(name="Balance Test", phone="0500000116", current_balance=Decimal("1500.00"))
        db_session.add(c)
        db_session.commit()
        assert c.balance == 1500.0

    def test_customer_password_setter_and_checker(self, db_session):
        from models import Customer
        c = Customer(name="Password Test", phone="0500000117")
        c.set_password("secret123")
        db_session.add(c)
        db_session.commit()
        assert c.check_password("secret123") is True
        assert c.check_password("wrong") is False
        with pytest.raises(AttributeError):
            _ = c.password

    def test_customer_password_empty_check(self, db_session):
        from models import Customer
        c = Customer(name="No Pass", phone="0500000118")
        db_session.add(c)
        db_session.commit()
        assert c.check_password("anything") is False

    def test_customer_is_valid_email(self, db_session):
        from models import Customer
        c1 = Customer(name="Valid Email", phone="0500000119", email="test@example.com")
        db_session.add(c1)
        db_session.commit()
        assert c1.is_valid_email() is True
        c2 = Customer(name="No Email", phone="0500000120")
        db_session.add(c2)
        db_session.commit()
        assert c2.is_valid_email() is False

    def test_customer_to_dict(self, db_session):
        from models import Customer
        c = Customer(name="Dict Test", phone="0500000121", email="dict@test.com",
                      address="Test St", discount_rate=Decimal("5.00"), credit_limit=Decimal("2000.00"))
        db_session.add(c)
        db_session.commit()
        d = c.to_dict()
        assert d["name"] == "Dict Test"
        assert d["phone"] == "0500000121"
        assert d["email"] == "dict@test.com"
        assert d["address"] == "Test St"
        assert d["category"] == "عادي"
        assert d["discount_rate"] == 5.0
        assert d["credit_limit"] == 2000.0
        assert d["balance"] == 0.0
        assert d["is_active"] is True
        assert d["is_archived"] is False
        assert "created_at" in d

    def test_customer_repr(self, db_session):
        from models import Customer
        c = Customer(name="Repr Test", phone="0500000122")
        db_session.add(c)
        db_session.commit()
        assert repr(c) == "<Customer Repr Test>"

    def test_customer_zero_opening_balance_default(self, db_session):
        from models import Customer
        c = Customer(name="Opening Bal", phone="0500000123")
        db_session.add(c)
        db_session.commit()
        assert c.opening_balance == 0

    def test_customer_credit_status_active(self, db_session):
        from models import Customer
        c = Customer(name="Active Credit", phone="0500000124", credit_limit=Decimal("1000.00"))
        c.current_balance = Decimal("500.00")
        db_session.add(c)
        db_session.commit()
        assert c.credit_status == "نشط"

    def test_customer_credit_status_suspended(self, db_session):
        from models import Customer
        c = Customer(name="Suspended Credit", phone="0500000125", credit_limit=Decimal("1000.00"))
        c.current_balance = Decimal("1500.00")
        db_session.add(c)
        db_session.commit()
        assert c.credit_status == "معلق"

    def test_customer_credit_status_no_limit(self, db_session):
        from models import Customer
        c = Customer(name="No Limit", phone="0500000126", credit_limit=Decimal("0.00"))
        c.current_balance = Decimal("99999.00")
        db_session.add(c)
        db_session.commit()
        assert c.credit_status == "نشط"

    def test_customer_get_id(self, db_session):
        from models import Customer
        c = Customer(name="GetID Test", phone="0500000127")
        db_session.add(c)
        db_session.commit()
        assert c.get_id() == f"c:{c.id}"

    def test_customer_default_timestamps(self, db_session):
        from models import Customer
        c = Customer(name="Timestamps", phone="0500000128")
        db_session.add(c)
        db_session.commit()
        assert c.created_at is not None
        assert c.updated_at is not None
