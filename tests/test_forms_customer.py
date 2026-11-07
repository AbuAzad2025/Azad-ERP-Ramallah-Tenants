from decimal import Decimal
import pytest
from werkzeug.datastructures import MultiDict
from forms import CustomerForm


def _formdata(**kwargs):
    """Build a MultiDict for form submission simulation (bypasses CSRF)."""
    items = list(kwargs.items())
    return MultiDict(items)


class TestCustomerForm:
    """Tests for CustomerForm validation and behavior."""

    FORM_META = {"csrf": False}

    def test_valid_form(self, db_session):
        form = CustomerForm(
            _formdata(name="Test Customer", phone="+970599999999",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_missing_name(self, db_session):
        form = CustomerForm(
            _formdata(name="", phone="0500000101",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_missing_phone(self, db_session):
        form = CustomerForm(
            _formdata(name="No Phone", phone="",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "phone" in form.errors

    def test_missing_currency(self, db_session):
        form = CustomerForm(
            _formdata(name="Test", phone="0500000102",
                      category="عادي", currency=""),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "currency" in form.errors

    def test_invalid_email(self, db_session):
        form = CustomerForm(
            _formdata(name="Bad Email", phone="0500000103",
                      email="not-an-email",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_phone_normalization(self, db_session):
        form = CustomerForm(
            _formdata(name="Phone Norm", phone="  0599 999 999  ",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.phone.data == "0599999999"

    def test_phone_with_plus_prefix(self, db_session):
        form = CustomerForm(
            _formdata(name="Phone Plus", phone="+972-59-999-9999",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.phone.data == "+972599999999"

    def test_email_normalization(self, db_session):
        form = CustomerForm(
            _formdata(name="Email Norm", phone="0500000104",
                      email="  Test@Example.COM  ",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.email.data == "test@example.com"

    def test_password_optional_field_bypasses_validate_password(self, db_session):
        """Optional() stops chain for empty password; validate_password never runs."""
        form = CustomerForm(
            _formdata(name="New Customer", phone="0500000105",
                      category="عادي", currency="ILS",
                      password=""),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.password.data == ""

    def test_validate_password_raises_when_empty_on_create(self, db_session):
        """Direct call to validate_password rejects empty password on create."""
        from wtforms.validators import ValidationError
        form = CustomerForm(
            _formdata(name="New Customer", phone="0500000105",
                      category="عادي", currency="ILS",
                      password=""),
            meta=self.FORM_META,
        )
        with pytest.raises(ValidationError, match="كلمة المرور مطلوبة عند إنشاء زبون جديد"):
            form.validate_password(form.password)

    def test_password_optional_on_edit(self, db_session):
        form = CustomerForm(
            _formdata(id="1", name="Edit Customer", phone="0500000106",
                      category="عادي", currency="ILS",
                      password=""),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_password_min_length(self, db_session):
        form = CustomerForm(
            _formdata(name="Short Pwd", phone="0500000107",
                      category="عادي", currency="ILS",
                      password="ab"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "password" in form.errors

    def test_negative_credit_limit(self, db_session):
        form = CustomerForm(
            _formdata(name="Neg Credit", phone="0500000108",
                      category="عادي", currency="ILS",
                      credit_limit="-10"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "credit_limit" in form.errors

    def test_credit_limit_zero(self, db_session):
        form = CustomerForm(
            _formdata(name="Zero Credit", phone="0500000109",
                      category="عادي", currency="ILS",
                      credit_limit="0"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_discount_rate_over_100(self, db_session):
        form = CustomerForm(
            _formdata(name="High Disc", phone="0500000110",
                      category="عادي", currency="ILS",
                      discount_rate="150"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "discount_rate" in form.errors

    def test_duplicate_phone_rejected(self, db_session):
        from models import Customer
        existing = Customer(name="Existing", phone="0500000111")
        db_session.add(existing)
        db_session.commit()

        form = CustomerForm(
            _formdata(name="Duplicate Phone", phone="0500000111",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "phone" in form.errors

    def test_duplicate_email_rejected(self, db_session):
        from models import Customer
        existing = Customer(name="Existing", phone="0500000112", email="dup@test.com")
        db_session.add(existing)
        db_session.commit()

        form = CustomerForm(
            _formdata(name="Duplicate Email", phone="0500000113",
                      email="dup@test.com",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_same_phone_allowed_on_edit(self, db_session):
        from models import Customer
        existing = Customer(name="Existing", phone="0500000114")
        db_session.add(existing)
        db_session.commit()

        form = CustomerForm(
            _formdata(id=str(existing.id), name="Existing", phone="0500000114",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_apply_to_basic(self, db_session):
        from models import Customer
        form = CustomerForm(
            _formdata(name="Applied Customer", phone="0500000115",
                      email="applied@test.com",
                      category="ذهبي", currency="USD", is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        c = Customer()
        form.apply_to(c)
        assert c.name == "Applied Customer"
        assert c.currency == "USD"
        assert c.category == "ذهبي"
        assert c.is_active is True

    def test_apply_to_sets_password(self, db_session):
        from models import Customer
        form = CustomerForm(
            _formdata(name="Pwd Customer", phone="0500000116",
                      category="عادي", currency="ILS",
                      password="secret123"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        c = Customer()
        form.apply_to(c)
        assert c.password_hash is not None
        assert c.check_password("secret123") is True

    def test_apply_to_optional_fields_default(self, db_session):
        from models import Customer
        form = CustomerForm(
            _formdata(name="Minimal", phone="0500000117",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        c = Customer()
        form.apply_to(c)
        assert c.address is None
        assert c.notes is None
        assert c.email is None
        assert c.credit_limit == Decimal("0")
        assert c.discount_rate == Decimal("0")

    def test_whatsapp_fallback_to_phone(self, db_session):
        """Empty whatsapp stays None (Optional stops chain); apply_to applies fallback."""
        from models import Customer
        form = CustomerForm(
            _formdata(name="WA Fallback", phone="0500000118",
                      category="عادي", currency="ILS",
                      whatsapp=""),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.whatsapp.data is None
        c = Customer()
        form.apply_to(c)
        assert c.whatsapp == "0500000118"

    def test_whatsapp_separate_value(self, db_session):
        form = CustomerForm(
            _formdata(name="WA Separate", phone="0500000119",
                      category="عادي", currency="ILS",
                      whatsapp="0599999999"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.whatsapp.data == "0599999999"

    def test_notes_max_length(self, db_session):
        form = CustomerForm(
            _formdata(name="Long Notes", phone="0500000120",
                      category="عادي", currency="ILS",
                      notes="x" * 501),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "notes" in form.errors

    def test_default_category_is_normal(self, db_session):
        form = CustomerForm(
            _formdata(name="Default Cat", phone="0500000121",
                      currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.category.data == "عادي"

    def test_phone_name_too_long(self, db_session):
        form = CustomerForm(
            _formdata(name="Normal", phone="0" * 21,
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "phone" in form.errors

    def test_name_max_length(self, db_session):
        form = CustomerForm(
            _formdata(name="a" * 101, phone="0500000122",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_confirm_password_mismatch(self, db_session):
        form = CustomerForm(
            _formdata(name="Confirm Test", phone="0500000123",
                      category="عادي", currency="ILS",
                      password="secret123", confirm="different"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "confirm" in form.errors

    def test_all_optional_fields_empty(self, db_session):
        form = CustomerForm(
            _formdata(name="All Optional Empty", phone="0500000124",
                      category="عادي", currency="ILS",
                      email="", address="", whatsapp="", notes="",
                      credit_limit="", discount_rate="", opening_balance=""),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_phone_empty_after_normalize_raises(self, db_session):
        form = CustomerForm(
            _formdata(name="Test", phone="   ",
                      category="عادي", currency="ILS"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "phone" in form.errors


class TestCustomerFormOnline:
    def test_customer_form_online_imports(self):
        from forms import CustomerFormOnline
        assert CustomerFormOnline is not None


class TestCustomerImportForm:
    def test_customer_import_form_imports(self):
        from forms import CustomerImportForm
        assert CustomerImportForm is not None
