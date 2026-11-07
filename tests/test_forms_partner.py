from decimal import Decimal
from werkzeug.datastructures import MultiDict


def _fd(**kw):
    return MultiDict(list(kw.items()))


class TestPartnerForm:
    FORM_META = {"csrf": False}

    def test_valid_form(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Test Partner", phone_number="0500000400", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_missing_name(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="", phone_number="0500000401", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_missing_currency(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Test", phone_number="0500000402", currency=""),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "currency" in form.errors

    def test_phone_normalization(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Test", phone_number="  050 123 4567  ", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.phone_number.data == "0501234567"

    def test_email_normalization(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Test", phone_number="0500000403",
                email="  Test@Example.COM  ", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.email.data == "test@example.com"

    def test_invalid_email(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Test", phone_number="0500000404",
                email="not-an-email", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_apply_to_basic(self, db_session):
        from models import Partner
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Applied Partner", phone_number="0500000405",
                email="partner@test.com", currency="USD",
                identity_number="ID002", share_percentage="25"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        p = Partner()
        form.apply_to(p)
        assert p.name == "Applied Partner"
        assert p.currency == "USD"
        assert p.identity_number == "ID002"
        assert p.share_percentage == Decimal("25.00")

    def test_apply_to_optional_defaults(self, db_session):
        from models import Partner
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Minimal", phone_number="0500000406", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        p = Partner()
        form.apply_to(p)
        assert p.contact_info is None
        assert p.address is None
        assert p.notes is None
        assert p.opening_balance == Decimal("0")

    def test_duplicate_phone(self, db_session):
        from models import Partner
        from forms import PartnerForm
        db_session.add(Partner(name="Existing", phone_number="0500000407"))
        db_session.commit()
        form = PartnerForm(
            _fd(name="Dup Phone", phone_number="0500000407", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "phone_number" in form.errors

    def test_duplicate_email(self, db_session):
        from models import Partner
        from forms import PartnerForm
        db_session.add(Partner(name="Existing", email="dup@partner.com"))
        db_session.commit()
        form = PartnerForm(
            _fd(name="Dup Email", phone_number="0500000408",
                email="dup@partner.com", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_share_percentage_over_100(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="High Share", phone_number="0500000409",
                currency="ILS", share_percentage="150"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "share_percentage" in form.errors

    def test_share_percentage_zero(self, db_session):
        from forms import PartnerForm
        form = PartnerForm(
            _fd(name="Zero Share", phone_number="0500000410",
                currency="ILS", share_percentage="0"),
            meta=self.FORM_META,
        )
        assert form.validate() is True


class TestQuickPartnerForm:
    FORM_META = {"csrf": False}

    def test_valid_quick(self, db_session):
        from forms import QuickPartnerForm
        form = QuickPartnerForm(
            _fd(name="Quick", phone="0500000411"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_missing_name(self, db_session):
        from forms import QuickPartnerForm
        form = QuickPartnerForm(
            _fd(name="", phone="0500000412"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_phone_normalization(self, db_session):
        from forms import QuickPartnerForm
        form = QuickPartnerForm(
            _fd(name="Quick", phone="  059 888 8888  "),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.phone.data == "0598888888"
