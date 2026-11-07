from decimal import Decimal
from werkzeug.datastructures import MultiDict
from forms import SupplierForm


def _fd(**kw):
    return MultiDict(list(kw.items()))


class TestSupplierForm:
    FORM_META = {"csrf": False}

    def test_valid_form(self, db_session):
        form = SupplierForm(
            _fd(name="Test Supplier", phone="0500000300", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_missing_name(self, db_session):
        form = SupplierForm(
            _fd(name="", phone="0500000301", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_missing_currency(self, db_session):
        form = SupplierForm(
            _fd(name="Test", phone="0500000302", currency=""),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "currency" in form.errors

    def test_phone_normalization(self, db_session):
        form = SupplierForm(
            _fd(name="Test", phone="  050 123 4567  ", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.phone.data == "0501234567"

    def test_email_normalization(self, db_session):
        form = SupplierForm(
            _fd(name="Test", phone="0500000303",
                email="  Test@Example.COM  ", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.email.data == "test@example.com"

    def test_invalid_email(self, db_session):
        form = SupplierForm(
            _fd(name="Test", phone="0500000304",
                email="not-an-email", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_apply_to_basic(self, db_session):
        from models import Supplier
        form = SupplierForm(
            _fd(name="Applied Supplier", phone="0500000305",
                email="supplier@test.com", currency="USD",
                is_local="y", identity_number="ID001"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        s = Supplier()
        form.apply_to(s)
        assert s.name == "Applied Supplier"
        assert s.currency == "USD"
        assert s.is_local is True
        assert s.identity_number == "ID001"

    def test_apply_to_optional_fields_default(self, db_session):
        from models import Supplier
        form = SupplierForm(
            _fd(name="Minimal", phone="0500000306", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        s = Supplier()
        form.apply_to(s)
        assert s.contact is None
        assert s.address is None
        assert s.notes is None
        assert s.payment_terms is None
        assert s.opening_balance == Decimal("0")

    def test_duplicate_phone(self, db_session):
        from models import Supplier
        db_session.add(Supplier(name="Existing", phone="0500000307"))
        db_session.commit()
        form = SupplierForm(
            _fd(name="Dup Phone", phone="0500000307", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "phone" in form.errors

    def test_duplicate_email(self, db_session):
        from models import Supplier
        db_session.add(Supplier(name="Existing", email="dup@supplier.com"))
        db_session.commit()
        form = SupplierForm(
            _fd(name="Dup Email", phone="0500000308",
                email="dup@supplier.com", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_name_too_long(self, db_session):
        form = SupplierForm(
            _fd(name="x" * 101, phone="0500000309", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_optional_phone_accepted(self, db_session):
        form = SupplierForm(
            _fd(name="No Phone", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_negative_opening_balance(self, db_session):
        form = SupplierForm(
            _fd(name="Neg Balance", phone="0500000310",
                currency="ILS", opening_balance="-50"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.opening_balance.data == Decimal("-50.00")


class TestQuickSupplierForm:
    FORM_META = {"csrf": False}

    def test_valid_quick(self, db_session):
        from forms import QuickSupplierForm
        form = QuickSupplierForm(
            _fd(name="Quick", phone="0500000311"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_missing_name(self, db_session):
        from forms import QuickSupplierForm
        form = QuickSupplierForm(
            _fd(name="", phone="0500000312"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_phone_normalization(self, db_session):
        from forms import QuickSupplierForm
        form = QuickSupplierForm(
            _fd(name="Quick", phone="  059 999 9999  "),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.phone.data == "0599999999"
