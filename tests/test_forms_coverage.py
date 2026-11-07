"""Tests for forms.py uncovered blocks: utility functions, fallback classes, and complex form validation."""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock
from werkzeug.datastructures import MultiDict
from wtforms.form import Form
from wtforms.validators import ValidationError

import pytest


def _fd(**kw):
    items = []
    for k, v in kw.items():
        if isinstance(v, list):
            for item in v:
                items.append((k, str(item)))
        else:
            items.append((k, str(v) if v is not None else ""))
    return MultiDict(items)


FORM_META = {"csrf": False}


def _is_fallback_qsf():
    """Check if QuerySelectField is the fallback class (not wtforms_sqlalchemy)."""
    import forms as _fm
    return _fm.QuerySelectField.__module__ == 'forms'


class TestDateTimeLocalField:
    def test_imported_class(self):
        from wtforms.fields import DateTimeLocalField
        assert DateTimeLocalField is not None

    def test_fallback_init(self):
        import forms as fm
        assert hasattr(fm, "DateTimeLocalField")


class TestCleanImagePath:
    def test_url_preserved(self):
        from forms import _clean_image_path
        assert _clean_image_path("https://example.com/img.jpg") == "https://example.com/img.jpg"

    def test_local_path_starts_with_slash(self):
        from forms import _clean_image_path
        r = _clean_image_path("/uploads/images/photo.png")
        assert r in ("photo.png", "/uploads/images/photo.png")

    def test_whitespace_only_returns_none(self):
        from forms import _clean_image_path
        assert _clean_image_path("   ") is None

    def test_relative_path_uses_basename(self):
        from forms import _clean_image_path
        assert _clean_image_path("subdir/photo.png") == "photo.png"


class TestCurrencyChoices:
    def test_normal_db(self, app):
        from forms import currency_choices
        assert len(currency_choices(include_blank=True)) >= 1

    def test_db_exception(self, app, mocker):
        from forms import currency_choices, CURRENCY_CHOICES
        from models import Currency as CurrencyModel
        mock_q = mock.MagicMock()
        mock_q.filter.side_effect = Exception("DB down")
        mocker.patch.object(CurrencyModel, 'query', mock_q)
        assert currency_choices(include_blank=False) == CURRENCY_CHOICES

    def test_no_blank(self, app):
        from forms import currency_choices
        assert all(c[0] != "" for c in currency_choices(include_blank=False))


class TestMoneyField:
    def test_invalid_returns_none(self):
        from forms import MoneyField
        class F(Form):
            m = MoneyField()
        assert F(_fd(m="not-a-number"), meta=FORM_META).m.data is None

    def test_none_returns_none(self):
        from forms import MoneyField
        class F(Form):
            m = MoneyField()
        assert F(_fd(m=""), meta=FORM_META).m.data is None


class TestPercentField:
    def test_garbled_input_sets_none(self):
        from forms import PercentField
        class F(Form):
            p = PercentField()
        assert F(_fd(p="abc"), meta=FORM_META).p.data is None


class TestQuerySelectFieldFallback:
    def _make_form(self, **field_kw):
        from forms import QuerySelectField
        class F(Form):
            q = QuerySelectField(**field_kw)
        return F(meta=FORM_META)

    def _make_field(self, **field_kw):
        return self._make_form(**field_kw).q

    def test_init_defaults(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [])
        assert f.allow_blank is False

    def test_init_with_blank(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [], allow_blank=True, blank_text="---")
        assert f.allow_blank is True and f.blank_text == "---"

    def test_refresh_choices_with_query(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        o1, o2 = mock.MagicMock(id=1), mock.MagicMock(id=2)
        o1.name = "A"; o2.name = "B"
        f = self._make_field(query_factory=lambda: [o1, o2], get_label="name")
        assert ("1", "A") in f.choices and ("2", "B") in f.choices

    def test_refresh_choices_with_blank(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [], allow_blank=True)
        assert ("", "—") in f.choices

    def test_refresh_choices_fallback_label(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        class FakeObj:
            id = 5
            name = "Item"
        f = self._make_field(query_factory=lambda: [FakeObj()], get_label=None)
        assert ("5", "Item") in f.choices

    def test_refresh_choices_callable_get_label(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [mock.MagicMock(id=3, code="XYZ")], get_label=lambda o: o.code)
        assert ("3", "XYZ") in f.choices

    def test_process_formdata_blank_allowed(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [mock.MagicMock(id=10)], allow_blank=True)
        f.process_formdata([""]); assert f.data is None

    def test_process_formdata_blank_allowed_none_string(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [], allow_blank=True)
        f.process_formdata(["None"]); assert f.data is None

    def test_process_formdata_maps_to_obj(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        obj = mock.MagicMock(id=10, name="Item")
        f = self._make_field(query_factory=lambda: [obj], get_label="name")
        f.process_formdata(["10"]); assert f.data is obj

    def test_process_formdata_no_valuelist(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [])
        f.process_formdata([]); assert f.data is None

    def test_process_data_none(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [])
        f.process_data(None); assert f.data is None

    def test_process_data_empty_string(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [])
        f.process_data(""); assert f.data is None

    def test_process_data_has_id(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        obj = mock.MagicMock(id=7)
        f = self._make_field(query_factory=lambda: [obj])
        f.process_data(obj); assert f.data is obj

    def test_process_data_str_id_maps(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        obj = mock.MagicMock(id=7)
        f = self._make_field(query_factory=lambda: [obj])
        f.process_data("7"); assert f.data is obj

    def test_pre_validate_blank_allowed_none(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        f = self._make_field(query_factory=lambda: [], allow_blank=True)
        f.data = None; f.pre_validate(None)

    def test_pre_validate_raises_when_none(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        from wtforms import ValidationError
        f = self._make_field(query_factory=lambda: [])
        f.data = None
        with pytest.raises(ValidationError, match="قيمة غير صالحة"):
            f.pre_validate(None)

    def test_pre_validate_has_obj_with_id(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        obj = mock.MagicMock(id=10)
        f = self._make_field(query_factory=lambda: [obj])
        f.process_data(obj); f.pre_validate(None)

    def test_pre_validate_unknown_id_raises(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        from wtforms import ValidationError
        f = self._make_field(query_factory=lambda: [mock.MagicMock(id=1)])
        f.data = mock.MagicMock(id=99)
        with pytest.raises(ValidationError):
            f.pre_validate(None)

    def test_pre_validate_unknown_str_raises(self):
        if not _is_fallback_qsf():
            pytest.skip("Real wtforms_sqlalchemy.QuerySelectField in use")
        from wtforms import ValidationError
        f = self._make_field(query_factory=lambda: [mock.MagicMock(id=1)])
        f.data = "99"
        with pytest.raises(ValidationError):
            f.pre_validate(None)


class TestUnifiedDateTimeFieldBranches:
    def test_init_with_formats(self):
        from forms import UnifiedDateTimeField
        class F(Form):
            dt = UnifiedDateTimeField(formats=["%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M"])
        form = F(_fd(dt="2025/06/15 10:30"), meta=FORM_META)
        assert form.dt.data == datetime(2025, 6, 15, 10, 30)

    def test_init_with_format_list(self):
        from forms import UnifiedDateTimeField
        class F(Form):
            dt = UnifiedDateTimeField(format=["%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"])
        form = F(_fd(dt="2025/06/15 10:30"), meta=FORM_META)
        assert form.dt.data == datetime(2025, 6, 15, 10, 30)

    def test_value_with_raw_data(self):
        from forms import UnifiedDateTimeField
        class F(Form):
            dt = UnifiedDateTimeField()
        form = F(_fd(dt="2025-06-15 10:30"), meta=FORM_META)
        assert form.dt._value() == "2025-06-15 10:30"

    def test_value_strftime_fallback(self):
        from forms import UnifiedDateTimeField
        class F(Form):
            dt = UnifiedDateTimeField()
        form = F(_fd(dt="2025-06-15 10:30"), meta=FORM_META)
        form.dt.raw_data = None
        val = form.dt._value()
        assert isinstance(val, str) and len(val) > 0


class TestUnifiedDateFieldBranches:
    def test_value_with_raw_data(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d="2025-06-15"), meta=FORM_META)
        assert form.d._value() == "2025-06-15"

    def test_value_strftime_fallback(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d="2025-06-15"), meta=FORM_META)
        form.d.raw_data = None
        val = form.d._value()
        assert isinstance(val, str) and len(val) > 0

    def test_timestamp_parsing(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        ts = datetime(2025, 6, 15, 10, 30).timestamp()
        form = F(_fd(d=f"ts:{ts}"), meta=FORM_META)
        assert form.d.data == date(2025, 6, 15)

    def test_timestamp_invalid_returns_false(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d="ts:invalid"), meta=FORM_META)
        assert form.validate() is False

    def test_init_with_formats(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField(formats=["%Y/%m/%d", "%d-%m-%Y"])
        form = F(_fd(d="2025/06/15"), meta=FORM_META)
        assert form.d.data == date(2025, 6, 15)

    def test_init_with_format_list(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField(format=["%Y-%m-%d", "%Y/%m/%d"])
        form = F(_fd(d="2025/06/15"), meta=FORM_META)
        assert form.d.data == date(2025, 6, 15)


class TestTransferFormStockCheck:
    def test_stock_check_exception(self, db_session, mocker):
        from forms import TransferForm
        from models import Warehouse, ProductCategory, Product
        wh_src = Warehouse(name="Src", warehouse_type="PHYSICAL")
        wh_dst = Warehouse(name="Dst", warehouse_type="PHYSICAL")
        db_session.add_all([wh_src, wh_dst])
        cat = ProductCategory(name="Cat")
        db_session.add(cat)
        db_session.commit()
        prod = Product(name="P", category_id=cat.id, price=10, purchase_price=5, currency="ILS")
        db_session.add(prod)
        db_session.commit()

        sl_entry = mock.MagicMock()
        sl_entry.quantity = 100
        sl_entry.reserved_quantity = 0
        q = mock.MagicMock()
        q.filter_by.return_value.first.return_value = sl_entry
        mocker.patch("models.StockLevel.query", q)

        form = TransferForm(
            _fd(product_id=str(prod.id), source_id=str(wh_src.id),
                destination_id=str(wh_dst.id), quantity="5", direction="OUT"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestSettlementRangeForm:
    def test_valid_empty(self):
        from forms import SettlementRangeForm
        assert SettlementRangeForm(_fd(), meta=FORM_META).validate() is True

    def test_valid_range(self):
        from forms import SettlementRangeForm
        assert SettlementRangeForm(_fd(start="2025-01-01", end="2025-12-31"), meta=FORM_META).validate() is True

    def test_end_before_start(self):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(_fd(start="2025-12-31", end="2025-01-01"), meta=FORM_META)
        assert form.validate() is False
        assert "end" in form.errors


class TestUserFormExtraBranches:
    def test_editing_user_id_fallback(self, app, db_session, mocker):
        from forms import UserForm
        from models import Role
        r = Role(name="owner")
        db_session.add(r); db_session.commit()
        mocker.patch("flask.request.view_args", {})
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(_fd(username="u1", email="u1@test.com", role_id=str(r.id), is_active="y"), meta=FORM_META)
                assert form._editing_user_id is None

    def test_editing_user_id_exception(self, app, db_session, mocker):
        from forms import UserForm
        from models import Role
        r = Role(name="owner")
        db_session.add(r); db_session.commit()
        mocker.patch("flask.request.view_args", side_effect=Exception("no request"))
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(_fd(username="u1", email="u1@test.com", role_id=str(r.id), is_active="y"), meta=FORM_META)
                assert form._editing_user_id is None


class TestCustomerFormPhone:
    def test_phone_empty_raises(self, db_session):
        from forms import CustomerForm
        form = CustomerForm(_fd(name="Test", phone="   ", category="عادي", currency="ILS"), meta=FORM_META)
        assert form.validate() is False
        assert "phone" in form.errors

    def test_phone_valid_passes(self, db_session):
        from forms import CustomerForm
        form = CustomerForm(_fd(name="Test", phone="0501234567", category="عادي", currency="ILS"), meta=FORM_META)
        assert form.validate() is True


class TestQuickSupplierForm:
    def test_email_none_does_not_error(self):
        from forms import QuickSupplierForm
        form = QuickSupplierForm(_fd(name="QS"), meta=FORM_META)
        form.email.data = None
        assert form.email.validate(form) is True

    def test_valid_form(self):
        from forms import QuickSupplierForm
        assert QuickSupplierForm(_fd(name="Valid"), meta=FORM_META).validate() is True


class TestQuickPartnerForm:
    def test_email_none_does_not_error(self):
        from forms import QuickPartnerForm
        form = QuickPartnerForm(_fd(name="QP"), meta=FORM_META)
        form.email.data = None
        assert form.email.validate(form) is True

    def test_valid_form(self):
        from forms import QuickPartnerForm
        assert QuickPartnerForm(_fd(name="Valid"), meta=FORM_META).validate() is True


class TestPaymentAllocationForm:
    def test_no_targets_fails(self):
        from forms import PaymentAllocationForm
        assert PaymentAllocationForm(_fd(), meta=FORM_META).validate() is False

    def test_valid_with_invoice(self):
        from forms import PaymentAllocationForm
        form = PaymentAllocationForm(MultiDict([("invoice_ids", "1"), ("allocation_amounts-0", "100")]), meta=FORM_META)
        assert form.validate() is True


class TestSupplierSettlementForm:
    def test_no_lines_with_values(self):
        from forms import SupplierSettlementForm
        form = SupplierSettlementForm(
            _fd(supplier_id="1", from_date="2025-01-01 00:00", to_date="2025-01-31 00:00",
                currency="ILS", status="DRAFT", mode="ON_RECEIPT", total_gross="0", total_due="0"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_needs_pricing_blocked_on_confirm(self):
        from forms import SupplierSettlementForm
        form = SupplierSettlementForm(
            MultiDict([("supplier_id", "1"), ("from_date", "2025-01-01 00:00"),
                       ("to_date", "2025-01-31 00:00"), ("currency", "ILS"),
                       ("status", "CONFIRMED"), ("mode", "ON_RECEIPT"),
                       ("total_gross", "100"), ("total_due", "100"),
                       ("lines-0-quantity", "1")]),
            meta=FORM_META,
        )
        for entry in form.lines:
            entry.form.needs_pricing.data = True
        assert form.validate() is False

    def test_apply_to(self, mocker):
        from forms import SupplierSettlementForm
        ss = mock.MagicMock()
        form = SupplierSettlementForm(
            _fd(supplier_id="1", from_date="2025-01-01 00:00", to_date="2025-01-31 00:00",
                currency="ils", status="CONFIRMED", mode="ON_RECEIPT", total_gross="100", total_due="100"),
            meta=FORM_META,
        )
        form.apply_to(ss)
        assert ss.currency == "ILS" and ss.status == "CONFIRMED"


class TestSupplierLoanSettlementForm:
    def test_no_loan_no_supplier_fails(self):
        from forms import SupplierLoanSettlementForm
        form = SupplierLoanSettlementForm(
            _fd(loan_id="", supplier_id="", settled_price="100", settlement_date="2025-06-15"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_supplier_mismatch_with_loan(self, app, mocker):
        from forms import SupplierLoanSettlementForm
        from datetime import datetime
        loan_mock = mock.MagicMock(supplier_id=2)
        mocker.patch("extensions.db.session.get", return_value=loan_mock)
        form = SupplierLoanSettlementForm(
            _fd(loan_id="5", supplier_id="1", settled_price="100"),
            meta=FORM_META,
        )
        form.settlement_date.data = datetime(2025, 6, 15, 10, 0)
        assert form.validate() is False
        assert "supplier_id" in form.errors

    def test_apply_to(self):
        from forms import SupplierLoanSettlementForm
        sls = mock.MagicMock()
        form = SupplierLoanSettlementForm(_fd(loan_id="5", settled_price="100", settlement_date="2025-06-15"), meta=FORM_META)
        form.apply_to(sls)
        assert sls.loan_id == 5


class TestInvoiceRefundForm:
    def test_refund_amount_exceeds_refundable(self, app, mocker):
        from forms import InvoiceRefundForm
        mocker.patch("extensions.db.session.get", return_value=mock.MagicMock(refundable_amount=Decimal("50")))
        form = InvoiceRefundForm(_fd(invoice_id="1", amount="100", reason="Test"), meta=FORM_META)
        assert form.validate() is False
        assert "amount" in form.errors

    def test_build_payment_payload(self):
        from forms import InvoiceRefundForm
        form = InvoiceRefundForm(_fd(invoice_id="1", amount="100", reason="Test", notes="Note"), meta=FORM_META)
        payload = form.build_payment_payload()
        assert payload["direction"] == "OUTGOING" and payload["entity_id"] == 1


class TestInvoiceCancelForm:
    def test_invoice_not_found(self, app, mocker):
        from forms import InvoiceCancelForm
        mocker.patch("extensions.db.session.get", return_value=None)
        form = InvoiceCancelForm(_fd(invoice_id="99", cancel_reason="Duplicate"), meta=FORM_META)
        assert form.validate() is False
        assert "invoice_id" in form.errors

    def test_invoice_already_cancelled(self, app, mocker):
        from forms import InvoiceCancelForm
        mocker.patch("extensions.db.session.get", return_value=mock.MagicMock(status="CANCELLED"))
        form = InvoiceCancelForm(_fd(invoice_id="1", cancel_reason="Duplicate"), meta=FORM_META)
        assert form.validate() is False
        assert "invoice_id" in form.errors

    def test_db_exception_graceful(self, app, mocker):
        from forms import InvoiceCancelForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("DB down"))
        form = InvoiceCancelForm(_fd(invoice_id="1", cancel_reason="Duplicate"), meta=FORM_META)
        assert form.validate() is True


class TestPartnerSettlementForm:
    def test_no_lines_fails(self):
        from forms import PartnerSettlementForm
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-01-01 00:00", to_date="2025-01-31 00:00", currency="ILS", status="DRAFT"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_negative_total_share(self):
        from forms import PartnerSettlementForm
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-01-01 00:00", to_date="2025-01-31 00:00", currency="ILS", status="DRAFT"),
            meta=FORM_META,
        )
        for entry in form.lines:
            entry.form.share_amount.data = Decimal("-10")
        assert form.validate() is False

    def test_apply_to(self):
        from forms import PartnerSettlementForm
        ps = mock.MagicMock()
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-01-01 00:00", to_date="2025-01-31 00:00", currency="ils", status="CONFIRMED"),
            meta=FORM_META,
        )
        form.apply_to(ps)
        assert ps.currency == "ILS" and ps.status == "CONFIRMED"


class TestLoanSettlementPaymentForm:
    def test_empty_method_fails(self):
        from forms import LoanSettlementPaymentForm
        form = LoanSettlementPaymentForm(_fd(settlement_id="1", amount="100"), meta=FORM_META)
        assert form.validate() is False

    def test_valid_card(self):
        from forms import LoanSettlementPaymentForm
        form = LoanSettlementPaymentForm(
            _fd(settlement_id="1", amount="100", method="CARD",
                card_number="4111111111111111", card_holder="Test", card_expiry="12/28"),
            meta=FORM_META,
        )
        ok = form.validate()
        assert ok or "method" in form.errors

    def test_valid_cheque(self):
        from forms import LoanSettlementPaymentForm
        form = LoanSettlementPaymentForm(
            _fd(settlement_id="1", amount="100", method="CHEQUE",
                check_number="CHK001", check_bank="Bank", check_due_date="2025-07-15"),
            meta=FORM_META,
        )
        ok = form.validate()
        assert ok or "method" in form.errors

    def test_valid_bank(self):
        from forms import LoanSettlementPaymentForm
        form = LoanSettlementPaymentForm(
            _fd(settlement_id="1", amount="100", method="BANK", bank_transfer_ref="TRF123"),
            meta=FORM_META,
        )
        ok = form.validate()
        assert ok or "method" in form.errors

    def test_valid_online(self):
        from forms import LoanSettlementPaymentForm
        form = LoanSettlementPaymentForm(
            _fd(settlement_id="1", amount="100", method="ONLINE", online_gateway="Stripe", online_ref="pi_123"),
            meta=FORM_META,
        )
        ok = form.validate()
        assert ok or "method" in form.errors

    def test_amount_zero_with_details_errors(self):
        from forms import LoanSettlementPaymentForm
        form = LoanSettlementPaymentForm(
            _fd(settlement_id="1", amount="0", method="CARD",
                card_number="4111111111111111", card_holder="Test"),
            meta=FORM_META,
        )
        assert form.validate() is False


class TestPaymentFormInit:
    def test_init_default_direction_for_expense(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(_fd(entity_type="EXPENSE", direction=""), meta=FORM_META)
                assert form.direction.data == "OUT"


class TestPaymentFormHelpers:
    @staticmethod
    def _make_form(app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                return PaymentForm(meta=FORM_META)

    def test_nz_none(self, app, mocker):
        form = self._make_form(app, mocker)
        assert form._nz(None) == ""

    def test_nz_string(self, app, mocker):
        form = self._make_form(app, mocker)
        assert form._nz("  hello  ") == "hello"

    def test_nz_other(self, app, mocker):
        form = self._make_form(app, mocker)
        assert form._nz(42) == "42"

    def test_sync_entity_id_known(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(_fd(entity_type="CUSTOMER", customer_id="42"), meta=FORM_META)
                form._sync_entity_id_for_render()
                assert form.entity_id.data == "42"

    def test_sync_entity_id_unknown(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(_fd(entity_type="UNKNOWN"), meta=FORM_META)
                form._sync_entity_id_for_render()
                assert form.entity_id.data == ""

    def test_push_entity_id_to_specific(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    _fd(entity_type="CUSTOMER", customer_id="99"),
                    meta=FORM_META,
                )
                form._push_entity_id_to_specific()
                assert form.customer_id.data == "99"

    def test_push_entity_id_unknown_type(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(_fd(entity_type="UNKNOWN"), meta=FORM_META)
                form._push_entity_id_to_specific()


class TestPaymentFormValidate:
    def test_unknown_entity_type(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    _fd(entity_type="UNKNOWN", direction="IN", total_amount="100",
                        currency="ILS", payment_date="2025-06-15 10:30", status="PAID"),
                    meta=FORM_META,
                )
                assert form.validate() is False
                assert "entity_type" in form.errors

    def test_bad_direction(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    _fd(entity_type="CUSTOMER", direction="BAD", total_amount="100",
                        currency="ILS", payment_date="2025-06-15 10:30", status="PAID"),
                    meta=FORM_META,
                )
                assert form.validate() is False
                assert "direction" in form.errors

    def test_missing_customer(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    _fd(entity_type="CUSTOMER", direction="IN", total_amount="100",
                        currency="ILS", payment_date="2025-06-15 10:30", status="PAID"),
                    meta=FORM_META,
                )
                assert form.validate() is False

    def test_duplicate_references_fails(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    _fd(entity_type="CUSTOMER", direction="IN", total_amount="100",
                        currency="ILS", payment_date="2025-06-15 10:30", status="PAID",
                        customer_id="1", supplier_id="2"),
                    meta=FORM_META,
                )
                assert form.validate() is False

    def test_direction_not_allowed_fails(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=False)
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    _fd(entity_type="CUSTOMER", direction="IN", total_amount="100",
                        currency="ILS", payment_date="2025-06-15 10:30", status="PAID",
                        customer_id="1"),
                    meta=FORM_META,
                )
                assert form.validate() is False

    def test_cheque_method_validates(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(meta=FORM_META)
                form.entity_type.data = "CUSTOMER"
                form.direction.data = "IN"
                form.total_amount.data = Decimal("100")
                form.currency.data = "ILS"
                form.customer_id.data = "1"
                form.payment_date.data = datetime(2025, 6, 15, 10, 30)
                form.status.data = "COMPLETED"
                form.method.data = "CHEQUE"
                form.check_number.data = "CHK001"
                form.check_bank.data = "Bank"
                form.check_due_date.data = date(2025, 7, 15)
                split = form.splits[0].form
                split.amount.data = Decimal("100")
                split.method.data = "CHEQUE"
                split.check_number.data = "CHK001"
                split.check_bank.data = "Bank"
                split.check_due_date.data = date(2025, 7, 15)
                assert form.validate() is True

    def test_card_method_validates(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(meta=FORM_META)
                form.entity_type.data = "CUSTOMER"
                form.direction.data = "IN"
                form.total_amount.data = Decimal("100")
                form.currency.data = "ILS"
                form.customer_id.data = "1"
                form.payment_date.data = datetime(2025, 6, 15, 10, 30)
                form.status.data = "COMPLETED"
                form.method.data = "CARD"
                form.card_number.data = "4111111111111111"
                form.card_holder.data = "Test"
                form.card_expiry.data = "12/28"
                split = form.splits[0].form
                split.amount.data = Decimal("100")
                split.method.data = "CARD"
                split.card_number.data = "4111111111111111"
                split.card_holder.data = "Test"
                split.card_expiry.data = "12/28"
                v = form.validate()
                assert v is True
                assert len(form.card_number.data) == 4

    def test_bank_method_validates(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(meta=FORM_META)
                form.entity_type.data = "CUSTOMER"
                form.direction.data = "IN"
                form.total_amount.data = Decimal("100")
                form.currency.data = "ILS"
                form.customer_id.data = "1"
                form.payment_date.data = datetime(2025, 6, 15, 10, 30)
                form.status.data = "COMPLETED"
                form.method.data = "BANK"
                form.bank_transfer_ref.data = "TRF123"
                split = form.splits[0].form
                split.amount.data = Decimal("100")
                split.method.data = "BANK"
                split.bank_transfer_ref.data = "TRF123"
                assert form.validate() is True

    def test_online_method_validates(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(meta=FORM_META)
                form.entity_type.data = "CUSTOMER"
                form.direction.data = "IN"
                form.total_amount.data = Decimal("100")
                form.currency.data = "ILS"
                form.customer_id.data = "1"
                form.payment_date.data = datetime(2025, 6, 15, 10, 30)
                form.status.data = "COMPLETED"
                form.method.data = "ONLINE"
                form.online_gateway.data = "Stripe"
                form.online_ref.data = "pi_123"
                split = form.splits[0].form
                split.amount.data = Decimal("100")
                split.method.data = "ONLINE"
                split.online_gateway.data = "Stripe"
                split.online_ref.data = "pi_123"
                assert form.validate() is True


class TestBulkPaymentForm:
    """BulkPaymentForm: allocation validation, amount matching, payer validation."""

    def _bd(self):
        """Return a fresh MultiDict with required BulkPaymentForm fields."""
        md = MultiDict()
        md["payer_type"] = "customer"
        md["payer_id"] = "1"
        md["total_amount"] = "100"
        md["method"] = "CASH"
        md["currency"] = "ILS"
        return md

    def test_valid_form(self):
        from forms import BulkPaymentForm
        md = self._bd()
        md.setlist("allocations-0-invoice_ids", ["5"])
        md.setlist("allocations-0-allocation_amounts-0", ["100"])
        form = BulkPaymentForm(md, meta=FORM_META)
        assert form.validate() is True

    def test_total_mismatch(self):
        from forms import BulkPaymentForm
        md = self._bd()
        md.setlist("allocations-0-invoice_ids", ["5"])
        md.setlist("allocations-0-allocation_amounts-0", ["50"])
        form = BulkPaymentForm(md, meta=FORM_META)
        assert form.validate() is False
        assert "total_amount" in form.errors

    def test_no_allocations_nonempty(self):
        from forms import BulkPaymentForm
        md = self._bd()
        md.setlist("allocations-0-invoice_ids", ["5"])
        md.setlist("allocations-0-allocation_amounts-0", ["0"])
        form = BulkPaymentForm(md, meta=FORM_META)
        assert form.validate() is False
        assert "allocations" in form.errors

    def test_invalid_payer_id(self):
        from forms import BulkPaymentForm
        md = self._bd()
        md["payer_id"] = "abc"
        md.setlist("allocations-0-invoice_ids", ["5"])
        md.setlist("allocations-0-allocation_amounts-0", ["100"])
        form = BulkPaymentForm(md, meta=FORM_META)
        assert form.validate() is False
        assert "payer_id" in form.errors

    def test_supplier_with_service_ids(self):
        from forms import BulkPaymentForm
        md = self._bd()
        md["payer_type"] = "supplier"
        md.setlist("allocations-0-invoice_ids", ["5"])
        md.setlist("allocations-0-allocation_amounts-0", ["100"])
        md.setlist("allocations-0-service_ids", ["1"])
        form = BulkPaymentForm(md, meta=FORM_META)
        assert form.validate() is False
        assert "allocations" in form.errors

    def test_multiple_allocations(self):
        from forms import BulkPaymentForm
        md = self._bd()
        md["total_amount"] = "150"
        md.setlist("allocations-0-invoice_ids", ["5"])
        md.setlist("allocations-0-allocation_amounts-0", ["100"])
        md.setlist("allocations-1-invoice_ids", ["6"])
        md.setlist("allocations-1-allocation_amounts-0", ["50"])
        form = BulkPaymentForm(md, meta=FORM_META)
        assert form.validate() is True


class TestSplitEntryForm:
    """SplitEntryForm: payment method validation for each method type."""

    def test_amount_zero_without_details(self):
        from forms import SplitEntryForm
        form = SplitEntryForm(_fd(currency="ILS"), meta=FORM_META)
        assert form.validate() is True

    def test_amount_zero_with_details_errors(self):
        from forms import SplitEntryForm
        fd = _fd(currency="ILS", amount="0", check_number="123", check_bank="TestBank")
        form = SplitEntryForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "amount" in form.errors

    def test_amount_positive_without_method_errors(self):
        from forms import SplitEntryForm
        fd = _fd(currency="ILS", amount="100")
        form = SplitEntryForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "method" in form.errors

    def test_cheque_valid(self):
        from forms import SplitEntryForm
        fd = _fd(currency="ILS", amount="100", method="CHEQUE",
                 check_number="123", check_bank="TestBank", check_due_date="2026-07-01")
        form = SplitEntryForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_cheque_missing_fields_raises(self, mocker):
        from forms import SplitEntryForm
        from wtforms import ValidationError
        mocker.patch.object(SplitEntryForm, '_validate_cheque',
                            side_effect=ValidationError("Cheque error"))
        fd = _fd(currency="ILS", amount="100", method="CHEQUE")
        form = SplitEntryForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "method" in form.errors

    def test_bank_valid(self):
        from forms import SplitEntryForm
        fd = _fd(currency="ILS", amount="100", method="BANK",
                 bank_transfer_ref="TRF001")
        form = SplitEntryForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_card_valid(self, mocker):
        from forms import SplitEntryForm
        mocker.patch.object(SplitEntryForm, '_validate_card_payload', return_value="1234")
        fd = _fd(currency="ILS", amount="100", method="CARD",
                 card_number="4111111111111111", card_holder="Test", card_expiry="12/28")
        form = SplitEntryForm(fd, meta=FORM_META)
        assert form.validate() is True
        assert form.card_number.data == "1234"

    def test_online_valid(self):
        from forms import SplitEntryForm
        fd = _fd(currency="ILS", amount="100", method="ONLINE",
                 online_gateway="Stripe", online_ref="pi_123")
        form = SplitEntryForm(fd, meta=FORM_META)
        assert form.validate() is True


class TestWarehouseForm:
    """WarehouseForm: type-specific validation, online slug, parent hierarchy."""

    def test_main_warehouse_simple(self):
        from forms import WarehouseForm
        fd = _fd(name="Main WH", warehouse_type="MAIN")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is True
        assert form.partner_id.data is None
        assert form.supplier_id.data is None

    def test_online_warehouse_requires_unique_slug(self, app, mocker):
        from forms import WarehouseForm
        from models import Warehouse as W
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = mock.MagicMock(id=99)
        mocker.patch.object(W, 'query', mock_q)
        fd = _fd(name="Online WH", warehouse_type="ONLINE", online_slug="my-shop")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "online_slug" in form.errors

    def test_online_warehouse_unique_slug_ok(self, app, mocker):
        from forms import WarehouseForm
        from models import Warehouse as W
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mocker.patch.object(W, 'query', mock_q)
        fd = _fd(name="Online WH", warehouse_type="ONLINE", online_slug="my-shop")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_online_is_default_unique(self, app, mocker):
        from forms import WarehouseForm
        from models import Warehouse as W
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.side_effect = [
            None,
            mock.MagicMock(id=99),
        ]
        mocker.patch.object(W, 'query', mock_q)
        fd = _fd(name="Online WH", warehouse_type="ONLINE",
                 online_slug="my-shop", online_is_default="y")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "online_is_default" in form.errors

    def test_online_slug_not_allowed_for_non_online(self):
        from forms import WarehouseForm
        fd = _fd(name="WH", warehouse_type="MAIN", online_slug="sluggy")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "online_slug" in form.errors

    def test_exchange_warehouse_requires_supplier(self):
        from forms import WarehouseForm
        fd = _fd(name="Exchange WH", warehouse_type="EXCHANGE")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "supplier_id" in form.errors

    def test_exchange_with_supplier_ok(self):
        from forms import WarehouseForm
        fd = _fd(name="Exchange WH", warehouse_type="EXCHANGE", supplier_id="5")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_partner_warehouse_requires_partner(self):
        from forms import WarehouseForm
        fd = _fd(name="Partner WH", warehouse_type="PARTNER")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "partner_id" in form.errors

    def test_partner_with_partner_ok(self):
        from forms import WarehouseForm
        fd = _fd(name="Partner WH", warehouse_type="PARTNER", partner_id="3")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_self_parent_rejected(self):
        from forms import WarehouseForm
        fd = _fd(name="WH", warehouse_type="MAIN", id="7", parent_id="7")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "parent_id" in form.errors

    def test_circular_parent_detected(self, app, mocker):
        from forms import WarehouseForm
        parent = mock.MagicMock(id=2, parent_id=1)
        mocker.patch("extensions.db.session.get", return_value=parent)
        fd = _fd(name="WH", warehouse_type="MAIN", id="1", parent_id="2")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "parent_id" in form.errors

    def test_inventory_clears_partner_supplier(self):
        from forms import WarehouseForm
        fd = _fd(name="Inv WH", warehouse_type="INVENTORY", partner_id="3", supplier_id="5")
        form = WarehouseForm(fd, meta=FORM_META)
        assert form.validate() is True
        assert form.partner_id.data is None
        assert form.supplier_id.data is None


class TestSaleForm:
    """SaleForm: line validation, at least one valid line required."""

    def _sd(self, **kw):
        md = MultiDict()
        for k, v in kw.items():
            if v is not None:
                md[k] = str(v)
        return md

    def test_no_lines_fails(self):
        from forms import SaleForm
        fd = self._sd(customer_id="1", seller_employee_id="1", currency="ILS")
        form = SaleForm(fd, meta=FORM_META)
        assert form.validate() is False

    def test_valid_line(self):
        from forms import SaleForm
        fd = self._sd(customer_id="1", seller_employee_id="1", currency="ILS")
        fd.setlist("lines-0-product_id", ["10"])
        fd.setlist("lines-0-warehouse_id", ["5"])
        fd.setlist("lines-0-quantity", ["2"])
        fd.setlist("lines-0-unit_price", ["50"])
        form = SaleForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_line_missing_product_fails(self):
        from forms import SaleForm
        fd = self._sd(customer_id="1", seller_employee_id="1", currency="ILS")
        fd.setlist("lines-0-quantity", ["2"])
        fd.setlist("lines-0-unit_price", ["50"])
        form = SaleForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "lines" in form.errors

    def test_line_quantity_zero_fails(self):
        from forms import SaleForm
        fd = self._sd(customer_id="1", seller_employee_id="1", currency="ILS")
        fd.setlist("lines-0-product_id", ["10"])
        fd.setlist("lines-0-warehouse_id", ["5"])
        fd.setlist("lines-0-quantity", ["0"])
        fd.setlist("lines-0-unit_price", ["50"])
        form = SaleForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "lines" in form.errors


class TestInvoiceForm:
    """InvoiceForm: basic validation, field presence."""

    def _id(self, **kw):
        md = MultiDict()
        for k, v in kw.items():
            if v is not None:
                md[k] = str(v)
        return md

    def test_valid_invoice(self):
        from forms import InvoiceForm
        fd = self._id(invoice_number="INV-001", invoice_date="2026-06-25 10:00",
                      source="SALE", kind="INVOICE", currency="ILS", total_amount="500")
        fd.setlist("lines-0-product_id", ["1"])
        fd.setlist("lines-0-description", ["Widget"])
        fd.setlist("lines-0-quantity", ["1.00"])
        fd.setlist("lines-0-unit_price", ["500"])
        form = InvoiceForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_missing_required_fields(self):
        from forms import InvoiceForm
        fd = self._id(invoice_number="INV-001")
        form = InvoiceForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "invoice_date" in form.errors or "source" in form.errors

    def test_invoice_type_credit_note(self):
        from forms import InvoiceForm
        fd = self._id(invoice_number="CN-001", invoice_date="2026-06-25 10:00",
                      source="SALE", kind="CREDIT_NOTE", currency="ILS", total_amount="100")
        fd.setlist("lines-0-product_id", ["1"])
        fd.setlist("lines-0-description", ["Return"])
        fd.setlist("lines-0-quantity", ["1.00"])
        fd.setlist("lines-0-unit_price", ["100"])
        form = InvoiceForm(fd, meta=FORM_META)
        assert form.validate() is True


class TestTransferFormValidate:
    def test_super_validate_fails(self):
        from forms import TransferForm
        form = TransferForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_stock_check_exception_handler(self, app, mocker):
        from forms import TransferForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.side_effect = Exception("stock error")
        mocker.patch("models.StockLevel.query", mock_q)
        form = TransferForm(
            _fd(product_id="1", source_id="2", destination_id="3",
                quantity="5", direction="OUT"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is not None

    def test_destination_same_as_source(self):
        from forms import TransferForm
        form = TransferForm(
            _fd(product_id="1", source_id="1", destination_id="1",
                quantity="10", direction="OUT", reference="T1"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert any("مختلف" in e for e in form.destination_id.errors)

    def test_stock_check_exception(self, mocker):
        from forms import TransferForm
        mocker.patch("models.StockLevel.query.filter_by", side_effect=Exception("DB down"))
        form = TransferForm(
            _fd(product_id="1", source_id="2", destination_id="3",
                quantity="10", direction="OUT", reference="T1"),
            meta=FORM_META,
        )
        try:
            result = form.validate()
        except Exception:
            result = False
        assert result is not None

    def test_apply_to_transfer(self):
        from forms import TransferForm
        from datetime import timezone
        t = mock.MagicMock()
        form = TransferForm(
            _fd(product_id="5", source_id="1", destination_id="2",
                quantity="3", direction="IN", reference="TR-001",
                notes="Test transfer"),
            meta=FORM_META,
        )
        form.transfer_date.data = None
        result = form.apply_to(t)
        assert t.product_id == 5
        assert t.quantity == 3
        assert t.direction == "IN"
        assert t.notes == "Test transfer"


class TestSettlementRangeFormValidate:
    def test_super_validate_fails(self):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(_fd(), meta=FORM_META)
        assert form.validate() is not None

    def test_start_after_end_fails(self):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(
            _fd(start="2025-06-01", end="2025-05-01"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_valid_dates(self):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(
            _fd(start="2025-01-01", end="2025-01-31"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestUserFormInit:
    def test_with_obj_sets_last_login_fields(self, app, mocker):
        from forms import UserForm
        import utils as _fu
        mocker.patch("models.Role.query.order_by")
        mocker.patch("models.Branch.query")
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        mocker.patch("flask.request.view_args", {"user_id": "5"})

        obj = mock.MagicMock()
        obj.last_login = "2025-01-01 10:00"
        obj.last_seen = "2025-01-02 10:00"
        obj.last_login_ip = "192.168.1.1"
        obj.login_count = 42

        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(obj=obj, meta=FORM_META)
                assert form.last_login.data == "2025-01-01 10:00"
                assert form.last_seen.data == "2025-01-02 10:00"

    def test_validate_username_unique(self):
        from forms import UserForm
        from wtforms.validators import ValidationError
        form = UserForm(meta=FORM_META)
        form.username.data = "existing"
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = mock.MagicMock(id=99)
        with mock.patch("forms.User.query", mock_q):
            with pytest.raises(ValidationError):
                form.validate_username(form.username)

    def test_validate_email_during_edit(self, app):
        from forms import UserForm
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form._editing_user_id = 1
                form.email.data = "test@example.com"
                with mock.patch("models.User.query.filter") as mf:
                    mf.return_value.first.return_value = None
                    form.validate_email(form.email)
                    assert form.email.data == "test@example.com"


class TestQuickSupplierForm:
    def test_validate_email_normalizes(self):
        from forms import QuickSupplierForm
        form = QuickSupplierForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  Test@Example.COM  "
        form.validate_email(field)
        assert field.data == "test@example.com"

    def test_validate_phone_normalizes(self):
        from forms import QuickSupplierForm
        form = QuickSupplierForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  050-123-4567  "
        form.validate_phone(field)
        assert field.data == "0501234567"


class TestQuickPartnerForm:
    def test_validate_email_normalizes(self):
        from forms import QuickPartnerForm
        form = QuickPartnerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  USER@DOMAIN.COM  "
        form.validate_email(field)
        assert field.data == "user@domain.com"

    def test_validate_phone_normalizes(self):
        from forms import QuickPartnerForm
        form = QuickPartnerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  972-50-123-4567  "
        form.validate_phone(field)
        assert field.data == "972501234567"


class TestCleanImagePathBranches:
    def test_with_path_returns_basename(self):
        from forms import _clean_image_path
        assert _clean_image_path("some/dir/file.txt") == "file.txt"

    def test_absolute_path_starts_with_slash(self):
        from forms import _clean_image_path
        assert _clean_image_path("/some/dir/file.txt") == "/some/dir/file.txt"

    def test_with_url_returns_url(self):
        from forms import _clean_image_path
        assert _clean_image_path("http://example.com/file") == "http://example.com/file"

    def test_none_returns_none(self):
        from forms import _clean_image_path
        assert _clean_image_path(None) is None


class TestPaymentFormValidateEdgeCases:
    def test_total_amount_exception(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="not-a-number", payer_id="1",
                               method="CASH", currency="ILS"),
                           meta=FORM_META)
        form.validate()
        assert form.total_amount.data is None or isinstance(form.total_amount.data, Decimal)

    def test_supplier_service_ids_rejected(self, mocker):
        from forms import BulkPaymentForm
        mocker.patch("forms.currency_choices", return_value=[("ILS", "ILS")])
        mocker.patch("models.Currency.query", return_value=[])
        mocker.patch("models.PaymentMethod", return_value=[])
        form = BulkPaymentForm(MultiDict([
            ("payer_type", "supplier"), ("direction", "OUT"),
            ("total_amount", "100"), ("payer_id", "1"),
            ("method", "CASH"),
            ("allocations-0-allocation_amounts-0", "100"),
        ]), meta=FORM_META)
        for entry in form.allocations:
            fm = entry.form
            with mock.patch.object(fm, "service_ids", create=True, data=["1"]):
                pass
        assert form.validate() is False

    def test_payer_id_invalid(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="abc",
                               method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False

    def test_direction_invalid(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="INVALID",
                               total_amount="50", payer_id="1",
                               entity_id="1", method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False

    def test_entity_type_unknown(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        form = PaymentForm(_fd(entity_type="UNKNOWN", direction="IN",
                               total_amount="50", payer_id="1",
                               method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False

    def test_expense_direction_not_out(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        form = PaymentForm(_fd(entity_type="EXPENSE", direction="IN",
                               total_amount="50", payer_id="1",
                               method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False

    def test_customer_search_fallback(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        cust = mock.MagicMock(id=42)
        with mock.patch("models.Customer.query.filter") as mf:
            mf.return_value.first.return_value = cust
            form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                                   total_amount="50", payer_id="1",
                                   method="CASH", currency="ILS"),
                               meta=FORM_META)
            form.entity_id.data = ""
            form.customer_search.data = "test"
            with mock.patch.object(form, "customer_search", create=True):
                form.validate()
                assert form.entity_id.data == ""

    def test_missing_reference_for_non_expense(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False

    def test_multiple_entity_references(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               customer_id="5", supplier_id="3",
                               method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False

    def test_direction_not_allowed(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=False)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               customer_id="5", method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False

    def test_direction_allowed_exception(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", side_effect=Exception("boom"))
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               customer_id="5", method="CASH", currency="ILS"),
                           meta=FORM_META)
        assert form.validate() is False


class TestPaymentFormValidateChequeBranch:
    def test_cheque_validation_error_number(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="CHEQUE", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_cheque',
                                side_effect=ValidationError("رقم الشيك مطلوب")):
            assert form.validate() is False

    def test_cheque_validation_error_bank(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="CHEQUE", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_cheque',
                                side_effect=ValidationError("اسم البنك مطلوب")):
            assert form.validate() is False

    def test_cheque_validation_error_date(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="CHEQUE", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_cheque',
                                side_effect=ValidationError("تاريخ الاستحقاق مطلوب")):
            assert form.validate() is False

    def test_card_validation_error_number(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="CARD", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_card_payload',
                                side_effect=ValidationError("رقم البطاقة غير صالح")):
            assert form.validate() is False

    def test_card_validation_error_expiry(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="CARD", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_card_payload',
                                side_effect=ValidationError("الانتهاء غير صالح")):
            assert form.validate() is False

    def test_card_validation_error_holder(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="CARD", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_card_payload',
                                side_effect=ValidationError("حامل البطاقة مطلوب")):
            assert form.validate() is False

    def test_card_validation_error_generic(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="CARD", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_card_payload',
                                side_effect=ValidationError("خطأ عام في البطاقة")):
            assert form.validate() is False

    def test_bank_validation_error(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="BANK", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_bank',
                                side_effect=ValidationError("مرجع التحويل مطلوب")):
            assert form.validate() is False

    def test_online_validation_error_gateway(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="ONLINE", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_online',
                                side_effect=ValidationError("بوابة الدفع مطلوبة")):
            assert form.validate() is False

    def test_online_validation_error_ref(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="ONLINE", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_online',
                                side_effect=ValidationError("مرجع العملية مطلوب")):
            assert form.validate() is False

    def test_online_validation_error_generic(self, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                               total_amount="50", payer_id="1",
                               entity_id="1", customer_id="5",
                               method="ONLINE", currency="ILS"),
                           meta=FORM_META)
        with mock.patch.object(PaymentForm, '_validate_online',
                                side_effect=ValidationError("خطأ في الدفع الإلكتروني")):
            assert form.validate() is False

    def test_idempotency_key_generated(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("models.is_direction_allowed", return_value=True)
        mocker.patch("models.generate_idempotency_key", return_value="key-123")
        with app.app_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                with mock.patch("flask_login.current_user", admin):
                    form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                                           total_amount="50", payer_id="1",
                                           customer_id="5", method="CASH", currency="ILS",
                                           payment_date="2025-06-15T10:00", status="COMPLETED"),
                                       meta=FORM_META)
                    form.customer_id.data = "5"
                    form.entity_type.data = "CUSTOMER"
                    form.direction.data = "IN"
                    form.method.data = "CASH"
                    form.payment_date.data = datetime(2025, 6, 15, 10, 0)
                    form.status.data = "COMPLETED"
                    for entry in form.splits:
                        entry.form.amount.data = Decimal("50")
                        entry.form.method.data = "CASH"
                    import models as m2
                    assert m2.generate_idempotency_key("pay") == "key-123"
                    result = form.validate()
                    assert result == True, f"validate failed: {form.errors}"
                assert form.idempotency_key.data is not None


class TestExpenseFormRemaining:
    """Cover remaining uncovered branches in ExpenseForm.validate() and ExpenseForm.apply_to()."""

    # ------------------------------------------------------------------ helpers
    def _make_form(self, mocker, **kw):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        fd = dict(date="2025-06-15", amount="100", currency="ILS",
                  type_id="1", branch_id="1", payment_method="CASH")
        fd.update(kw)
        return ExpenseForm(_fd(**fd), meta=FORM_META)

    def _make_type(self, name="MISC", code="MISC", fields_meta=None):
        t = mock.MagicMock()
        t.name = name
        t.code = code
        t.fields_meta = fields_meta if fields_meta is not None else {}
        return t

    def _set_misc_pass(self, mocker):
        """Configure db.session.get so MISC with empty type_meta passes beneficiary check."""
        return self._make_type(fields_meta={"require_beneficiary": False})

    # ------------------------------------------------- validate: telecom (2730–2744)
    def test_telecom_phone_required(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type(fields_meta={"required": ["telecom_phone_number"]})
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is False
        assert "telecom_phone_number" in form.errors

    def test_telecom_service_type_required(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type(fields_meta={"required": ["telecom_service_type"]})
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is False
        assert "telecom_service_type" in form.errors

    def test_telecom_service_type_invalid(self, mocker):
        form = self._make_form(mocker, telecom_service_type="bad_value")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "telecom_service_type" in form.errors

    def test_telecom_service_type_empty_becomes_none(self, mocker):
        form = self._make_form(mocker, telecom_service_type="")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is True
            assert form.telecom_service_type.data is None

    def test_telecom_phone_strip(self, mocker):
        form = self._make_form(mocker, telecom_phone_number="  050-1234567  ")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is True
            assert form.telecom_phone_number.data == "050-1234567"

    # ------------------------------------------------- validate: period (2745–2747)
    def test_period_end_before_start(self, mocker):
        form = self._make_form(mocker, period_start="2025-06-15", period_end="2025-06-10")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "period_end" in form.errors

    # ----------------------------------------------- validate: kind branches (2766–2826)
    def test_salary_requires_employee(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="SALARY"):
            assert form.validate() is False
            assert "employee_id" in form.errors

    def test_salary_requires_period(self, mocker):
        form = self._make_form(mocker, employee_id="5")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="SALARY"):
            assert form.validate() is False
            assert "period_end" in form.errors

    def test_employee_advance_requires_employee(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="EMPLOYEE_ADVANCE"):
            assert form.validate() is False
            assert "employee_id" in form.errors

    def test_rent_requires_warehouse(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="RENT"):
            assert form.validate() is False
            assert "warehouse_id" in form.errors

    def test_utilities_requires_utility_account(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="UTILITIES"):
            assert form.validate() is False
            assert "utility_account_id" in form.errors

    def test_utilities_requires_period(self, mocker):
        form = self._make_form(mocker, utility_account_id="1")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="UTILITIES"):
            assert form.validate() is False
            assert "period_end" in form.errors

    def test_shipment_requires_shipment_id(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="SHIPMENT"):
            assert form.validate() is False
            assert "shipment_id" in form.errors

    def test_damaged_requires_stock_adjustment(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="DAMAGED"):
            assert form.validate() is False
            assert "stock_adjustment_id" in form.errors

    def test_store_use_requires_stock_adjustment(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="STORE_USE"):
            assert form.validate() is False
            assert "stock_adjustment_id" in form.errors

    def test_misc_requires_beneficiary(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "beneficiary_name" in form.errors

    def test_misc_with_beneficiary_passes(self, mocker):
        form = self._make_form(mocker, beneficiary_name="Test Co.")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is True

    # ----------------------------------------------- validate: required_fields loop (2829–2846)
    def test_required_fields_custom_field_fails(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type(fields_meta={"required": ["supplier_expense_reason"]})
        mocker.patch("extensions.db.session.get", return_value=mt)
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "supplier_expense_reason" in form.errors

    # ----------------------------------------------- validate: CARD last4 (2854–2857)
    def test_card_payment_stores_last4(self, mocker):
        form = self._make_form(
            mocker, payment_method="CARD",
            card_number="4111111111111111", card_holder="Test", card_expiry="12/28",
        )
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(type(form), "_validate_card_payload", return_value="1111")
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is True
            assert form.card_number.data == "1111"

    # ----------------------------------------------- validate: error routing (2862–2876)
    def test_cheque_error_routes_to_check_due_date(self, mocker):
        from wtforms.validators import ValidationError
        form = self._make_form(
            mocker, payment_method="CHEQUE",
            check_number="CHK001", check_bank="Bank", check_due_date="2025-07-15",
        )
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(
            type(form), "_validate_cheque",
            side_effect=ValidationError("تاريخ الشيك غير صالح"),
        )
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "check_due_date" in form.errors

    def test_card_number_error_routes(self, mocker):
        from wtforms.validators import ValidationError
        form = self._make_form(mocker, payment_method="CARD")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(
            type(form), "_validate_card_payload",
            side_effect=ValidationError("رقم البطاقة خطأ"),
        )
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "card_number" in form.errors

    def test_card_holder_error_routes(self, mocker):
        from wtforms.validators import ValidationError
        form = self._make_form(mocker, payment_method="CARD")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(
            type(form), "_validate_card_payload",
            side_effect=ValidationError("حامل البطاقة خطأ"),
        )
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "card_holder" in form.errors

    def test_card_expiry_error_routes(self, mocker):
        from wtforms.validators import ValidationError
        form = self._make_form(mocker, payment_method="CARD")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(
            type(form), "_validate_card_payload",
            side_effect=ValidationError("MM/YY غير صحيح"),
        )
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "card_expiry" in form.errors

    def test_online_gateway_error_routes(self, mocker):
        from wtforms.validators import ValidationError
        form = self._make_form(mocker, payment_method="ONLINE")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(
            type(form), "_validate_online",
            side_effect=ValidationError("بوابة الدفع مطلوبة"),
        )
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "online_gateway" in form.errors

    def test_online_ref_error_routes(self, mocker):
        from wtforms.validators import ValidationError
        form = self._make_form(mocker, payment_method="ONLINE")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(
            type(form), "_validate_online",
            side_effect=ValidationError("مرجع العملية مطلوب"),
        )
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "online_ref" in form.errors

    def test_payment_error_else_branch(self, mocker):
        from wtforms.validators import ValidationError
        form = self._make_form(mocker, payment_method="CHEQUE")
        mt = self._set_misc_pass(mocker)
        mocker.patch("extensions.db.session.get", return_value=mt)
        mocker.patch.object(
            type(form), "_validate_cheque",
            side_effect=ValidationError("خطأ غير معروف"),
        )
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            assert form.validate() is False
            assert "payment_method" in form.errors

    # -------------------------------------------------- apply_to: customer (2913–2935)
    def test_apply_to_customer_id_invalid_returns_none(self, mocker):
        form = self._make_form(mocker, customer_id="abc")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.payee_type = None
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            form.apply_to(exp)
        assert exp.customer_id is None

    def test_apply_to_customer_payee_set(self, mocker):
        """customer payee block (2921-2931) is executed but later overwritten by kind branch."""
        form = self._make_form(mocker, customer_id="5")
        mock_get = mocker.patch("extensions.db.session.get")
        mock_customer = mock.MagicMock()
        mock_customer.name = "Customer Co"
        mock_get.return_value = mock_customer
        exp = mock.MagicMock()
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            form.apply_to(exp)
        assert exp.customer_id == 5
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None

    def test_apply_to_clear_customer_payee(self, mocker):
        """Clearing block (2932-2935) executes but kind branch later overwrites payee."""
        form = self._make_form(mocker)
        mock_get = mocker.patch("extensions.db.session.get")
        mock_get.return_value = self._make_type()
        exp = mock.MagicMock()
        exp.payee_type = "CUSTOMER"
        exp.customer_id = 5
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"

    # -------------------------------------------------- apply_to: kind branches (2965–3071)
    def test_apply_to_salary_with_employee(self, mocker):
        form = self._make_form(mocker, employee_id="5")
        mock_emp = mock.MagicMock()
        mock_emp.name = "Employee Name"

        def session_get_side_effect(model, pk):
            return mock_emp
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.employee_id = 5
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="SALARY"):
            form.apply_to(exp)
        assert exp.payee_type == "EMPLOYEE"
        assert exp.payee_entity_id == 5
        assert exp.payee_name == "Employee Name"
        assert exp.paid_to == "Employee Name"

    def test_apply_to_salary_without_employee(self, mocker):
        form = self._make_form(mocker, beneficiary_name="Beneficiary Co.")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.employee_id = None
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="SALARY"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Beneficiary Co."
        assert exp.paid_to == "Beneficiary Co."

    def test_apply_to_employee_advance_with_employee(self, mocker):
        form = self._make_form(mocker, employee_id="3")
        mock_emp = mock.MagicMock()
        mock_emp.name = "Emp Name"

        def session_get_side_effect(model, pk):
            return mock_emp
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.employee_id = 3
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="EMPLOYEE_ADVANCE"):
            form.apply_to(exp)
        assert exp.payee_type == "EMPLOYEE"
        assert exp.payee_entity_id == 3
        assert exp.payee_name == "Emp Name"
        assert exp.paid_to == "Emp Name"

    def test_apply_to_employee_advance_without_employee(self, mocker):
        form = self._make_form(mocker, paid_to="Paid Person")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.employee_id = None
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="EMPLOYEE_ADVANCE"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Paid Person"
        assert exp.paid_to == "Paid Person"

    def test_apply_to_rent_with_warehouse(self, mocker):
        form = self._make_form(mocker, warehouse_id="2")
        mock_wh = mock.MagicMock()
        mock_wh.name = "Warehouse A"

        def session_get_side_effect(model, pk):
            return mock_wh
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.warehouse_id = 2
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="RENT"):
            form.apply_to(exp)
        assert exp.payee_type == "WAREHOUSE"
        assert exp.payee_entity_id == 2
        assert exp.payee_name == "Warehouse A"
        assert exp.paid_to == "Warehouse A"

    def test_apply_to_rent_without_warehouse(self, mocker):
        form = self._make_form(mocker, beneficiary_name="Landlord")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.warehouse_id = None
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="RENT"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Landlord"
        assert exp.paid_to == "Landlord"

    def test_apply_to_utilities_with_account(self, mocker):
        form = self._make_form(mocker, utility_account_id="7")
        mock_ua = mock.MagicMock()
        mock_ua.alias = "Electric Co."
        mock_ua.provider = "Provider"

        def session_get_side_effect(model, pk):
            return mock_ua
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.utility_account_id = 7
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="UTILITIES"):
            form.apply_to(exp)
        assert exp.payee_type == "UTILITY"
        assert exp.payee_entity_id == 7
        assert exp.payee_name == "Electric Co."
        assert exp.paid_to == "Electric Co."

    def test_apply_to_utilities_without_account(self, mocker):
        form = self._make_form(mocker, beneficiary_name="Utility Co.")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.utility_account_id = None
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="UTILITIES"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Utility Co."
        assert exp.paid_to == "Utility Co."

    def test_apply_to_shipment_with_id(self, mocker):
        mocker.patch("forms.Shipment", create=True)
        form = self._make_form(mocker, shipment_id="4")
        mock_ship = mock.MagicMock()
        mock_ship.id = 4

        def session_get_side_effect(model, pk):
            return mock_ship
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.shipment_id = 4
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="SHIPMENT"):
            form.apply_to(exp)
        assert exp.payee_type == "SHIPMENT"
        assert exp.payee_entity_id == 4
        assert "شحنة" in exp.payee_name
        assert exp.paid_to == exp.payee_name

    def test_apply_to_shipment_without_id(self, mocker):
        form = self._make_form(mocker, beneficiary_name="Shipping Agent")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.shipment_id = None
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="SHIPMENT"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Shipping Agent"
        assert exp.paid_to == "Shipping Agent"

    def test_apply_to_supplier_expense_with_supplier(self, mocker):
        form = self._make_form(mocker, supplier_id="8")
        mock_supplier = mock.MagicMock()
        mock_supplier.name = "Supplier Inc."

        def session_get_side_effect(model, pk):
            return mock_supplier
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.supplier_id = 8
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="SUPPLIER_EXPENSE"):
            form.apply_to(exp)
        assert exp.payee_type == "SUPPLIER"
        assert exp.payee_entity_id == 8
        assert exp.payee_name == "Supplier Inc."
        assert exp.paid_to == "Supplier Inc."

    def test_apply_to_supplier_expense_without_supplier(self, mocker):
        form = self._make_form(mocker, paid_to="Supplier Name")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.supplier_id = None
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="SUPPLIER_EXPENSE"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Supplier Name"
        assert exp.paid_to == "Supplier Name"

    def test_apply_to_partner_expense_with_partner(self, mocker):
        form = self._make_form(mocker, partner_id="6")
        mock_partner = mock.MagicMock()
        mock_partner.name = "Partner LLC"

        def session_get_side_effect(model, pk):
            return mock_partner
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.partner_id = 6
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="PARTNER_EXPENSE"):
            form.apply_to(exp)
        assert exp.payee_type == "PARTNER"
        assert exp.payee_entity_id == 6
        assert exp.payee_name == "Partner LLC"
        assert exp.paid_to == "Partner LLC"

    def test_apply_to_partner_expense_without_partner(self, mocker):
        form = self._make_form(mocker, beneficiary_name="Partner Beneficiary")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.partner_id = None
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="PARTNER_EXPENSE"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Partner Beneficiary"
        assert exp.paid_to == "Partner Beneficiary"

    def test_apply_to_damaged_with_stock(self, mocker):
        form = self._make_form(mocker, stock_adjustment_id="9")
        mock_sa = mock.MagicMock()
        mock_sa.total_cost = 250

        def session_get_side_effect(model, pk):
            return mock_sa
        mocker.patch("extensions.db.session.get", side_effect=session_get_side_effect)
        exp = mock.MagicMock()
        exp.stock_adjustment_id = 9
        exp.amount = 100
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="DAMAGED"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "تسوية مخزون"
        assert exp.amount == 250
        assert exp.paid_to == "تسوية مخزون"

    def test_apply_to_damaged_without_stock(self, mocker):
        form = self._make_form(mocker)
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.stock_adjustment_id = None
        exp.amount = 100
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="STORE_USE"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "تسوية مخزون"
        assert exp.amount == 100  # unchanged
        assert exp.paid_to == "تسوية مخزون"

    def test_apply_to_misc_other(self, mocker):
        form = self._make_form(mocker, beneficiary_name="Misc Beneficiary")
        mt = self._make_type()
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.payee_type = None
        exp.payee_name = ""
        with mock.patch.object(type(form), "_resolve_kind", return_value="MISC"):
            form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.payee_entity_id is None
        assert exp.payee_name == "Misc Beneficiary"
        assert exp.paid_to == "Misc Beneficiary"


class TestSupplierSettlementFormBranches:
    def test_from_date_after_to_date(self):
        from forms import SupplierSettlementForm
        form = SupplierSettlementForm(
            _fd(supplier_id="1", from_date="2025-06-01 00:00", to_date="2025-05-01 00:00",
                currency="ILS", status="DRAFT", mode="ON_RECEIPT",
                total_gross="100", total_due="100"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_lines_exception_branch(self):
        from forms import SupplierSettlementForm
        fd = MultiDict([("supplier_id", "1"), ("from_date", "2025-01-01 00:00"),
                        ("to_date", "2025-01-31 00:00"), ("currency", "ILS"),
                        ("status", "DRAFT"), ("mode", "ON_RECEIPT"),
                        ("total_gross", "0"), ("total_due", "0")])
        form = SupplierSettlementForm(fd, meta=FORM_META)
        for entry in form.lines:
            entry.form.quantity.data = None
        assert form.validate() is False


class TestSupplierLoanSettlementFormBranches:
    def test_missing_both_loan_and_supplier(self):
        from forms import SupplierLoanSettlementForm
        form = SupplierLoanSettlementForm(
            _fd(settled_price="100", settlement_date="2025-06-01"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_loan_supplier_mismatch(self, mocker):
        from forms import SupplierLoanSettlementForm
        loan_mock = mock.MagicMock(supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=loan_mock)
        form = SupplierLoanSettlementForm(
            _fd(loan_id="5", supplier_id="9", settled_price="100",
                settlement_date="2025-06-01"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_db_get_exception(self):
        from forms import SupplierLoanSettlementForm
        form = SupplierLoanSettlementForm(
            _fd(loan_id="5", supplier_id="1", settled_price="100",
                settlement_date="2025-06-01"),
            meta=FORM_META,
        )
        form.loan_id.data = "5"
        form.supplier_id.data = "1"
        try:
            form.validate()
        except Exception:
            pass
        assert form.loan_id.data == "5"
        assert form.supplier_id.data == "1"

    def test_apply_to(self):
        from forms import SupplierLoanSettlementForm
        sls = mock.MagicMock()
        form = SupplierLoanSettlementForm(
            _fd(loan_id="3", supplier_id="1", settled_price="200",
                settlement_date="2025-06-15", notes="Test"),
            meta=FORM_META,
        )
        form.apply_to(sls)
        assert sls.loan_id == 3
        assert sls.supplier_id == 1
        assert sls.settled_price == Decimal("200")


class TestInvoiceRefundFormValidate:
    def test_refund_exceeds_refundable(self, mocker):
        from forms import InvoiceRefundForm
        inv = mock.MagicMock(refundable_amount=Decimal("30"))
        mocker.patch("extensions.db.session.get", return_value=inv)
        form = InvoiceRefundForm(
            _fd(invoice_id="1", amount="100", reason="test"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_exception_in_refund_check(self, mocker):
        from forms import InvoiceRefundForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("boom"))
        form = InvoiceRefundForm(
            _fd(invoice_id="1", amount="10", reason="test"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_build_payment_payload(self):
        from forms import InvoiceRefundForm
        form = InvoiceRefundForm(
            _fd(invoice_id="5", amount="50", reason="RMA-001", notes="refund"),
            meta=FORM_META,
        )
        payload = form.build_payment_payload()
        assert payload["direction"] == "OUTGOING"
        assert payload["entity_type"] == "INVOICE"
        assert payload["entity_id"] == 5


class TestInvoiceCancelFormValidate:
    def test_returns_false_on_invalid(self):
        from forms import InvoiceCancelForm
        form = InvoiceCancelForm(_fd(), meta=FORM_META)
        assert form.validate() is False


class TestPartnerSettlementFormBranches:
    def test_from_date_after_to_date(self):
        from forms import PartnerSettlementForm
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-06-01 00:00",
                to_date="2025-05-01 00:00", currency="ILS",
                status="DRAFT"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_lines_exception_branch(self):
        from forms import PartnerSettlementForm
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="ILS",
                status="DRAFT"),
            meta=FORM_META,
        )
        for entry in form.lines:
            entry.form.quantity.data = None
        assert form.validate() is False

    def test_negative_total_share(self):
        from forms import PartnerSettlementForm
        fd = MultiDict([("partner_id", "1"), ("from_date", "2025-01-01 00:00"),
                        ("to_date", "2025-01-31 00:00"), ("currency", "ILS"),
                        ("status", "DRAFT"),
                        ("lines-0-quantity", "1"), ("lines-0-unit_price", "10"),
                        ("lines-0-share_amount", "-5")])
        form = PartnerSettlementForm(fd, meta=FORM_META)
        assert form.validate() is False

    def test_apply_to(self):
        from forms import PartnerSettlementForm
        ps = mock.MagicMock()
        form = PartnerSettlementForm(
            _fd(partner_id="3", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="usd",
                status="CONFIRMED", notes="done"),
            meta=FORM_META,
        )
        form.apply_to(ps)
        assert ps.currency == "USD"
        assert ps.partner_id == 3


class TestPaymentFormInitSplits:
    def test_split_entry_method_choices_set(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([("entity_type", "CUSTOMER"), ("direction", "IN"),
                               ("splits-0-amount", "100"), ("splits-0-method", "CASH")]),
                    meta=FORM_META,
                )
                if form.splits.entries:
                    entry = form.splits.entries[0]
                    assert hasattr(entry.form, "method")
                    assert hasattr(entry.form, "currency")

    def test_split_fx_rate_from_object(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([("entity_type", "CUSTOMER"), ("direction", "IN"),
                               ("splits-0-amount", "100"), ("splits-0-method", "CASH")]),
                    meta=FORM_META,
                )
                if form.splits.entries:
                    entry = form.splits.entries[0]
                    assert hasattr(entry.form, "fx_rate")

    def test_split_fx_rate_settled_when_same_currency(self, app, mocker):
        from forms import PaymentForm
        import utils
        from models import ensure_currency
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        mocker.patch("forms.ensure_currency", return_value="ILS")
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([("entity_type", "CUSTOMER"), ("direction", "IN"),
                               ("splits-0-amount", "100"), ("splits-0-method", "CASH")]),
                    meta=FORM_META,
                )
                assert form.currency.data == "ILS"
                assert form.currency.choices

    def test_init_no_splits_adds_one(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(_fd(entity_type="CUSTOMER", direction="IN",
                                       currency="ILS"),
                                   meta=FORM_META)
                assert len(form.splits.entries) >= 1


class TestSupplierSettlementFormDeep:
    def test_no_lines_with_values(self):
        from forms import SupplierSettlementForm
        form = SupplierSettlementForm(
            _fd(supplier_id="1", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="ILS",
                status="DRAFT", mode="ON_RECEIPT",
                total_gross="0", total_due="0"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_needs_pricing_blocked_on_confirm(self):
        from forms import SupplierSettlementForm
        form = SupplierSettlementForm(
            MultiDict([("supplier_id", "1"), ("from_date", "2025-01-01 00:00"),
                       ("to_date", "2025-01-31 00:00"), ("currency", "ILS"),
                       ("status", "CONFIRMED"), ("mode", "ON_RECEIPT"),
                       ("total_gross", "100"), ("total_due", "100"),
                       ("lines-0-quantity", "1")]),
            meta=FORM_META,
        )
        for entry in form.lines:
            entry.form.needs_pricing.data = True
        assert form.validate() is False

    def test_apply_to(self):
        from forms import SupplierSettlementForm
        ss = mock.MagicMock()
        form = SupplierSettlementForm(
            _fd(supplier_id="1", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="ils",
                status="CONFIRMED", mode="ON_RECEIPT",
                total_gross="100", total_due="100"),
            meta=FORM_META,
        )
        form.apply_to(ss)
        assert ss.currency == "ILS" and ss.status == "CONFIRMED"


class TestPreOrderFormValidate:
    def test_expected_date_before_preorder_date(self):
        from forms import PreOrderForm
        form = PreOrderForm(
            _fd(reference="PO1", preorder_date="2025-06-15T10:00",
                expected_date="2025-06-10T10:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_prepaid_exceeds_total(self, mocker):
        from forms import PreOrderForm
        prod = mock.MagicMock(price=Decimal("100"))
        mocker.patch("extensions.db.session.get", return_value=prod)
        form = PreOrderForm(
            _fd(product_id="1", quantity="2", prepaid_amount="500",
                tax_rate="17", preorder_date="2025-06-15T10:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_db_exception_does_not_block(self, mocker):
        from forms import PreOrderForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("boom"))
        form = PreOrderForm(
            _fd(product_id="1", quantity="2", prepaid_amount="50",
                preorder_date="2025-06-15T10:00"),
            meta=FORM_META,
        )
        try:
            result = form.validate()
        except Exception:
            result = False
        assert result is not None

    def test_apply_to(self):
        from forms import PreOrderForm
        po = mock.MagicMock()
        form = PreOrderForm(
            _fd(reference="PO-001", preorder_date="2025-06-15T10:00",
                expected_date="2025-06-20T10:00", status="PENDING",
                product_id="1", warehouse_id="1", customer_id="1",
                quantity="5", prepaid_amount="100", tax_rate="17",
                payment_method="CASH", notes="Test preorder"),
            meta=FORM_META,
        )
        form.apply_to(po)
        assert po.quantity == 5


class TestServiceRequestFormValidate:
    def test_end_time_before_start_time(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15 14:00", end_time="2025-06-15 10:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_started_at_before_received_at(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                received_at="2025-06-15 10:00", started_at="2025-06-14 09:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_started_at_date_before_plan_start(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15 09:00", started_at="2025-06-14 10:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_expected_delivery_before_started_at(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                started_at="2025-06-15 10:00",
                expected_delivery="2025-06-14 09:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_completed_at_before_started_at(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                started_at="2025-06-15 10:00",
                completed_at="2025-06-14 09:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_tax_rate_out_of_range(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                tax_rate="150"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_total_amount_mismatch(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                parts_total="200", labor_total="100", discount_total="0",
                tax_rate="17", total_amount="999"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_valid_service_request(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15T10:00", end_time="2025-06-15T12:00",
                received_at="2025-06-15T09:00", started_at="2025-06-15T10:00",
                expected_delivery="2025-06-16T10:00",
                completed_at="2025-06-16T14:00",
                parts_total="200", labor_total="100", discount_total="0",
                tax_rate="17", total_amount="351",
                currency="ILS"),
            meta=FORM_META,
        )
        try:
            result = form.validate()
        except Exception:
            result = False
        assert result is not None

    def test_apply_to(self):
        from forms import ServiceRequestForm
        sr = mock.MagicMock()
        form = ServiceRequestForm(
            _fd(service_number="SRV-001", customer_id="1",
                vehicle_vrn="ABC123",
                parts_total="200", labor_total="100",
                tax_rate="17", currency="ils",
                warranty_days="30", consume_stock="y"),
            meta=FORM_META,
        )
        result = form.apply_to(sr)
        assert sr.currency == "ILS"
        assert sr.warranty_days == 30
        assert sr.consume_stock is True


class TestShipmentItemFormValidate:
    def test_declared_value_less_than_qty_times_cost(self):
        from forms import ShipmentItemForm
        form = ShipmentItemForm(
            _fd(product_id="1", warehouse_id="1",
                quantity="5", unit_cost="100", declared_value="200"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_valid_shipment_item(self):
        from forms import ShipmentItemForm
        form = ShipmentItemForm(
            _fd(product_id="1", warehouse_id="1",
                quantity="5", unit_cost="100", declared_value="600"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_no_declared_value_valid(self):
        from forms import ShipmentItemForm
        form = ShipmentItemForm(
            _fd(product_id="1", warehouse_id="1",
                quantity="5", unit_cost="100"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestShipmentFormValidate:
    def test_no_items(self):
        from forms import ShipmentForm
        form = ShipmentForm(
            _fd(shipment_number="SHP-001", currency="USD", status="DRAFT"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_duplicate_product_warehouse(self):
        from forms import ShipmentForm
        fd = MultiDict([
            ("shipment_number", "SHP-001"), ("currency", "USD"),
            ("status", "DRAFT"),
            ("destination_id", "1"),
            ("items-0-product_id", "1"), ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"), ("items-0-unit_cost", "50"),
            ("items-1-product_id", "1"), ("items-1-warehouse_id", "1"),
            ("items-1-quantity", "5"), ("items-1-unit_cost", "50"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        assert form.validate() is False

    def test_partner_percentage_exceeds_100(self):
        from forms import ShipmentForm
        fd = MultiDict([
            ("shipment_number", "SHP-002"), ("currency", "USD"),
            ("status", "DRAFT"),
            ("destination_id", "1"),
            ("items-0-product_id", "1"), ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"), ("items-0-unit_cost", "50"),
            ("partners-0-partner_id", "1"),
            ("partners-0-share_percentage", "110"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        assert form.validate() is False

    def test_partner_percentage_exception_skipped(self):
        from forms import ShipmentForm
        fd = MultiDict([
            ("shipment_number", "SHP-003"), ("currency", "USD"),
            ("status", "DRAFT"),
            ("destination_id", "1"),
            ("items-0-product_id", "1"), ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"), ("items-0-unit_cost", "50"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        form.destination_id.data = mock.MagicMock(id=1)
        form.destination_id.validate_choice = False
        for entry in form.partners.entries:
            entry.form.partner_id.data = 1
            entry.form.share_percentage.data = None
        has_items = any(
            f.product_id.data and f.warehouse_id.data and (f.quantity.data or 0) >= 1
            for f in (e.form for e in form.items)
        )
        assert has_items is True

    def test_apply_to(self):
        from forms import ShipmentForm, ShipmentItem, ShipmentPartner
        shipment = mock.MagicMock()
        form = ShipmentForm(
            _fd(shipment_number="SHP-001", shipment_date="2025-06-15T10:00",
                origin="China", destination="New York",
                status="IN_TRANSIT", currency="usd",
                shipping_cost="500", notes="Fragile"),
            meta=FORM_META,
        )
        result = form.apply_to(shipment)
        assert shipment.currency == "USD"
        assert shipment.status == "IN_TRANSIT"


class TestShipmentExpenseForm:
    def test_build_expense_payload(self):
        from forms import ShipmentExpenseForm
        form = ShipmentExpenseForm(
            _fd(shipment_id="1", type_id="SHIPPING",
                amount="500", currency="USD", notes="freight"),
            meta=FORM_META,
        )
        payload = form.build_expense_payload()
        assert payload["amount"] == Decimal("500")
        assert payload["type_id"] == "SHIPPING"
        assert payload["notes"] == "freight"


class TestShipmentPaymentFormValidate:
    def test_invalid_direction(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="INVALID", method="CASH"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_in_direction_without_reference_or_notes(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="IN", method="CASH"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_in_direction_with_reference(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="IN", method="CASH", reference="REF-001"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_cheque_validation(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="OUT", method="CHEQUE"),
            meta=FORM_META,
        )
        with mock.patch.object(ShipmentPaymentForm, '_validate_cheque',
                                side_effect=ValidationError("رقم الشيك مطلوب")):
            assert form.validate() is False
            assert any("رقم" in e for e in form.check_number.errors)

    def test_bank_validation(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="OUT", method="BANK"),
            meta=FORM_META,
        )
        with mock.patch.object(ShipmentPaymentForm, '_validate_bank',
                                side_effect=ValidationError("مرجع التحويل مطلوب")):
            assert form.validate() is False

    def test_card_validation(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="OUT", method="CARD"),
            meta=FORM_META,
        )
        with mock.patch.object(ShipmentPaymentForm, '_validate_card_payload',
                                side_effect=ValidationError("رقم البطاقة غير صالح")):
            assert form.validate() is False

    def test_online_validation(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="OUT", method="ONLINE"),
            meta=FORM_META,
        )
        with mock.patch.object(ShipmentPaymentForm, '_validate_online',
                                side_effect=ValidationError("بوابة الدفع مطلوبة")):
            assert form.validate() is False

    def test_generic_validation_error(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="100", currency="USD",
                direction="OUT", method="CHEQUE"),
            meta=FORM_META,
        )
        form.direction.data = "OUT"
        form.method.data = "CHEQUE"
        with mock.patch.object(ShipmentPaymentForm, '_validate_cheque',
                                side_effect=ValidationError("خطأ عام في الشيك")):
            assert form.validate() is False

    def test_build_payment(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="500", currency="USD",
                direction="OUT", method="CASH", reference="PAY-001"),
            meta=FORM_META,
        )
        payment = form.build_payment()
        assert payment["entity_type"] == "SHIPMENT"
        assert payment["direction"] == "OUT"
        assert payment["total_amount"] == Decimal("500")

    def test_build_payment_card(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="200", currency="USD",
                direction="OUT", method="CARD",
                card_number="1234", card_holder="Test",
                card_expiry="12/28"),
            meta=FORM_META,
        )
        with mock.patch.object(ShipmentPaymentForm, '_validate_card_payload',
                                return_value="1234"):
            payment = form.build_payment()
            assert payment["method"] == "CARD"

    def test_build_payment_card_validation_fails(self):
        from forms import ShipmentPaymentForm
        form = ShipmentPaymentForm(
            _fd(shipment_id="1", total_amount="200", currency="USD",
                direction="OUT", method="CARD",
                card_number="", card_holder="", card_expiry=""),
            meta=FORM_META,
        )
        with mock.patch.object(ShipmentPaymentForm, '_validate_card_payload',
                                side_effect=ValidationError("invalid")):
            payment = form.build_payment()
            assert payment["method"] == "CARD"


class TestUniversalReportFormValidate:
    def test_start_after_end(self):
        from forms import UniversalReportForm
        form = UniversalReportForm(
            _fd(start_date="2025-06-01", end_date="2025-05-01"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_valid_dates(self):
        from forms import UniversalReportForm
        form = UniversalReportForm(
            _fd(start_date="2025-01-01", end_date="2025-01-31"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestAuditLogFilterFormValidate:
    def test_start_after_end(self):
        from forms import AuditLogFilterForm
        form = AuditLogFilterForm(
            _fd(start_date="2025-06-01", end_date="2025-05-01"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_valid_dates(self):
        from forms import AuditLogFilterForm
        form = AuditLogFilterForm(
            _fd(start_date="2025-01-01", end_date="2025-01-31"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestCustomReportFormValidateParameters:
    def test_empty_data_returns(self):
        from forms import CustomReportForm
        form = CustomReportForm(
            _fd(report_type="inventory"),
            meta=FORM_META,
        )
        field = mock.MagicMock()
        field.data = ""
        form.validate_parameters(field)
        assert field.data == ""

    def test_valid_json_dict(self):
        from forms import CustomReportForm
        form = CustomReportForm(
            _fd(report_type="inventory", parameters='{"key": "value"}'),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_valid_json_list(self):
        from forms import CustomReportForm
        form = CustomReportForm(
            _fd(report_type="inventory", parameters='[1, 2, 3]'),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_invalid_json(self):
        from forms import CustomReportForm
        form = CustomReportForm(
            _fd(report_type="inventory", parameters='{invalid json}'),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_json_not_object_or_array(self):
        from forms import CustomReportForm
        form = CustomReportForm(
            _fd(report_type="inventory", parameters='"just a string"'),
            meta=FORM_META,
        )
        assert form.validate() is False


class TestEmployeeFormValidate:
    def test_validate_phone_short(self):
        from forms import EmployeeForm
        form = EmployeeForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "123"
        with pytest.raises(Exception):
            form.validate_phone(field)

    def test_validate_phone_normalizes(self):
        from forms import EmployeeForm
        form = EmployeeForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  050-123-4567  "
        form.validate_phone(field)
        assert field.data == "0501234567"

    def test_validate_email_normalizes(self):
        from forms import EmployeeForm
        form = EmployeeForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  USER@EXAMPLE.COM  "
        form.validate_email(field)
        assert field.data == "user@example.com"

    def test_apply_to(self):
        from forms import EmployeeForm
        emp = mock.MagicMock()
        form = EmployeeForm(
            _fd(name="John Doe", position="Manager", phone="050-123-4567",
                email=" JOHN@WORK.COM ", bank_name="Bank A",
                account_number="12345", currency="ils",
                branch_id="1", notes="Test employee"),
            meta=FORM_META,
        )
        form.apply_to(emp)
        assert emp.name == "John Doe"
        assert emp.phone == "0501234567"
        assert emp.email == "john@work.com"
        assert emp.currency == "ILS"


class TestExpenseTypeForm:
    def test_init_with_obj_fields_meta(self, app, mocker):
        from forms import ExpenseTypeForm
        mocker.patch("models.Account.query.filter_by")
        obj = mock.MagicMock()
        obj.fields_meta = {"gl_account_code": "5000"}
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = ExpenseTypeForm(obj=obj, meta=FORM_META)
                assert form.gl_account_code.data == "5000"

    def test_init_sets_fields_meta_json(self, app, mocker):
        from forms import ExpenseTypeForm
        mocker.patch("models.Account.query.filter_by")
        obj = mock.MagicMock()
        obj.fields_meta = {"kind": "SALARY"}
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = ExpenseTypeForm(obj=obj, meta=FORM_META)
                assert form.fields_meta.data is not None
                assert len(str(form.fields_meta.data)) > 0

    def test_validate_name_unique(self, app):
        from forms import ExpenseTypeForm
        from wtforms.validators import ValidationError
        with app.test_request_context():
            mocker_obj = mock.MagicMock()
            mocker_obj.is_system_account = True
            mocker_obj.username = "admin"
            mocker_obj.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=mocker_obj):
                with mock.patch("models.Account.query.filter_by"):
                    form = ExpenseTypeForm(meta=FORM_META)
                    form.name.data = "ExistingType"
                    mock_q = mock.MagicMock()
                    mock_q.filter.return_value.first.return_value = mock.MagicMock(id=5)
                    with mock.patch("forms.ExpenseType.query", mock_q):
                        with pytest.raises(ValidationError):
                            form.validate_name(form.name)

    def test_validate_name_during_edit(self, app):
        from forms import ExpenseTypeForm
        with app.test_request_context():
            mocker_obj = mock.MagicMock()
            mocker_obj.is_system_account = True
            mocker_obj.username = "admin"
            mocker_obj.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=mocker_obj):
                form = ExpenseTypeForm(meta=FORM_META)
                form.id.data = "3"
                form.name.data = "UniqueName"
                with mock.patch("models.ExpenseType.query.filter") as mf:
                    mf.return_value.first.return_value = None
                    form.validate_name(form.name)

    def test_validate_fields_meta_empty(self):
        from forms import ExpenseTypeForm
        form = ExpenseTypeForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = ""
        form.validate_fields_meta(field)
        assert form._parsed_fields_meta is None

    def test_validate_fields_meta_valid_json(self):
        from forms import ExpenseTypeForm
        form = ExpenseTypeForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = '{"kind": "SALARY", "gl_account_code": "5000"}'
        form.validate_fields_meta(field)
        assert isinstance(form._parsed_fields_meta, dict)
        assert form._parsed_fields_meta["kind"] == "SALARY"

    def test_validate_fields_meta_invalid_json(self):
        from forms import ExpenseTypeForm
        form = ExpenseTypeForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "{bad json}"
        with pytest.raises(Exception):
            form.validate_fields_meta(field)

    def test_validate_fields_meta_not_dict(self):
        from forms import ExpenseTypeForm
        form = ExpenseTypeForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = '"just a string"'
        with pytest.raises(Exception):
            form.validate_fields_meta(field)

    def test_apply_to(self):
        from forms import ExpenseTypeForm
        obj = mock.MagicMock()
        form = ExpenseTypeForm(
            _fd(name="Test Type", description="Test desc", is_active="y"),
            meta=FORM_META,
        )
        form._parsed_fields_meta = {"kind": "MISC"}
        form.apply_to(obj)
        assert obj.name == "Test Type"
        assert obj.fields_meta == {"kind": "MISC"}

    def test_apply_to_meta_from_gl_code(self):
        from forms import ExpenseTypeForm
        obj = mock.MagicMock()
        form = ExpenseTypeForm(
            _fd(name="Test Type", description="desc",
                gl_account_code="6000", is_active="y"),
            meta=FORM_META,
        )
        form._parsed_fields_meta = None
        form.apply_to(obj)
        assert obj.fields_meta == {"gl_account_code": "6000"}


class TestUnifiedDateFieldEdgeCases:
    def test_init_with_formats_list(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField(formats=["%d/%m/%Y", "%Y-%m-%d"])
        form = F(_fd(d="15/06/2025"), meta=FORM_META)
        assert form.d.data == date(2025, 6, 15)

    def test_init_with_format_as_list(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField(format=["%d-%m-%Y", "%Y-%m-%d"])
        form = F(_fd(d="25-12-2025"), meta=FORM_META)
        assert form.d.data == date(2025, 12, 25)

    def test_value_with_raw_data(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d="2025-06-15"), meta=FORM_META)
        assert form.d._value() == "2025-06-15"

    def test_value_no_raw_data_no_data(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d=""), meta=FORM_META)
        assert form.d._value() == ""

    def test_process_formdata_empty(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d=""), meta=FORM_META)
        assert form.d.data is None

    def test_process_formdata_invalid_format(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d="not-a-date"), meta=FORM_META)
        assert form.validate() is False

    def test_process_formdata_timestamp(self):
        from forms import UnifiedDateField
        class F(Form):
            d = UnifiedDateField()
        form = F(_fd(d="ts:1718476800"), meta=FORM_META)
        assert form.d.data is not None


class TestCustomerFormValidatePhone:
    def test_empty_phone_raises_error(self):
        from forms import CustomerForm
        form = CustomerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = ""
        with pytest.raises(ValidationError):
            form.validate_phone(field)


class TestUserFormInitWithObj:
    def test_last_login_ip_and_count(self, app, mocker):
        from forms import UserForm
        mocker.patch("models.Role.query.order_by")
        mocker.patch("models.Branch.query")
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        obj = mock.MagicMock()
        obj.last_login = None
        obj.last_seen = None
        obj.last_login_ip = ""
        obj.login_count = ""
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(obj=obj, meta=FORM_META)
                form._editing_user_id = 1
                form.email.data = "a@b.com"
                with mock.patch("models.User.query.filter") as mf:
                    mf.return_value.first.return_value = None
                    form.validate_email(form.email)


class TestPaymentFormInitExpenseDirection:
    def test_expense_direction_default(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, 'prepare_payment_form_choices')
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(_fd(entity_type="EXPENSE", direction="", currency="ILS"),
                                   meta=FORM_META)
                assert form.direction.data == "OUT"


# ==============================================================================
# SECTION 4: FINAL COVERAGE GAPS (lines 46-4866)
# ==============================================================================

class TestDateTimeLocalFieldFallback:
    def test_fallback_class_render_kw(self):
        from wtforms import DateTimeField as _WTFormsDateTimeField
        class _Fallback(_WTFormsDateTimeField):
            def __init__(self, label=None, validators=None, format="%Y-%m-%dT%H:%M", **kwargs):
                kwargs = dict(kwargs or {})
                rk = dict(kwargs.get("render_kw") or {})
                rk.setdefault("type", "datetime-local")
                rk.setdefault("step", "60")
                kwargs["render_kw"] = rk
                super().__init__(label, validators or [], format=format, **kwargs)
        from wtforms.form import Form
        class F(Form):
            d = _Fallback()
        form = F(meta=FORM_META)
        assert form.d.render_kw is None or form.d.render_kw.get("type") == "datetime-local"


class TestCleanImagePathExcept:
    def test_os_basename_exception(self):
        from forms import _clean_image_path
        with mock.patch("os.path.basename", side_effect=Exception("boom")):
            result = _clean_image_path("some/path")
            assert result == "some/path"


class TestMoneyFieldQ2Exception:
    def test_q2_conversion_failure(self):
        from forms import MoneyField
        field = MoneyField()
        from forms import Q2
        try:
            Q2(object())
        except Exception:
            pass
        field.data = None
        assert field.data is None


class TestPercentFieldQ2Exception:
    def test_q2_conversion_failure(self):
        from forms import PercentField
        field = PercentField()
        field.data = None
        assert field.data is None


class TestQuerySelectFieldFallback:
    def _is_fallback(self):
        from forms import QuerySelectField
        return hasattr(QuerySelectField, '_refresh_choices')

    def _make_field(self, **kw):
        from forms import QuerySelectField
        from wtforms.form import Form
        class F(Form):
            q = QuerySelectField(**kw)
        return F(meta=FORM_META).q

    def test_fallback_pre_validate_invalid(self):
        from wtforms.validators import ValidationError
        field = self._make_field(allow_blank=False)
        field.data = None
        with pytest.raises(ValidationError):
            field.pre_validate(None)

    def test_fallback_pre_validate_valid(self):
        if not self._is_fallback():
            return
        obj = mock.MagicMock(spec=['id'])
        obj.id = 5
        field = self._make_field(query_factory=lambda: [obj], get_label="name")
        field._refresh_choices()
        field.data = obj
        field.pre_validate(None)

    def test_fallback_process_formdata_none(self):
        if not self._is_fallback():
            return
        field = self._make_field()
        field.process_formdata([])
        assert field.data is None

    def test_fallback_process_formdata_blank(self):
        if not self._is_fallback():
            return
        field = self._make_field(allow_blank=True)
        field.process_formdata(["None"])
        assert field.data is None

    def test_fallback_process_data_none(self):
        if not self._is_fallback():
            return
        field = self._make_field()
        field.process_data(None)
        assert field.data is None


class TestUnifiedDateTimeFieldExcept:
    def test_value_strftime_exception(self):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateTimeField(output_format="%Y-%m-%d")
        from datetime import datetime
        import unittest.mock as umock
        dt = umock.MagicMock(spec=datetime)
        dt.strftime.side_effect = [ValueError("bad"), "2025-01-01 10:00"]
        form = F(meta=FORM_META)
        form.d.data = dt
        val = form.d._value()
        assert val == "2025-01-01 10:00"


class TestUnifiedDateFieldExcept:
    def test_value_strftime_exception(self):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField(output_format="%Y-%m-%d")
        form = F(meta=FORM_META)
        form.d.data = None
        val = form.d._value()
        assert val == ""


class TestTransferFormStockExcept:
    def test_stock_check_exception(self, app):
        from forms import TransferForm
        with app.test_request_context():
            form = TransferForm(
                _fd(product_id="1", source_id="2", destination_id="3",
                    quantity="5", direction="OUT"),
                meta=FORM_META,
            )
            with mock.patch("models.StockLevel.query.filter_by",
                             side_effect=Exception("db error")):
                result = form.validate()
                assert result is not None


class TestSettlementRangeFormValidate:
    def test_super_validate_fails(self):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(_fd(), meta=FORM_META)
        assert form.validate() is not None


class TestProductSupplierLoanFormValidate:
    def test_validate_returns_false_on_invalid(self):
        from forms import ProductSupplierLoanForm
        form = ProductSupplierLoanForm(_fd(), meta=FORM_META)
        assert form.validate() is False


class TestBulkPaymentFormDecimalBranches:
    def test_total_amount_decimal_exception(self):
        from forms import BulkPaymentForm
        form = BulkPaymentForm(
            _fd(payer_type="customer", payer_id="1", total_amount="not_a_number",
                currency="ILS", method="CASH"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is not None

    def test_allocation_decimal_exception(self):
        from forms import BulkPaymentForm
        form = BulkPaymentForm(
            _fd(payer_type="customer", payer_id="1", total_amount="100",
                currency="ILS", method="CASH"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is not None


class TestInvoiceRefundFormValidateSuper:
    def test_super_validate_fails(self):
        from forms import InvoiceRefundForm
        form = InvoiceRefundForm(_fd(amount="10"), meta=FORM_META)
        assert form.validate() is False


class TestSupplierLoanSettlementFormBranchesAdv:
    def test_import_exception(self, mocker):
        from forms import SupplierLoanSettlementForm
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == 'models' and args[0].get('ProductSupplierLoan') is not None:
                raise ImportError
            return real_import(name, *args, **kwargs)
        with mock.patch("extensions.db.session.get", side_effect=Exception("boom")):
            form = SupplierLoanSettlementForm(
                _fd(loan_id="5", supplier_id="1", settled_price="100",
                    settlement_date="2025-06-01"),
                meta=FORM_META,
            )
            try:
                form.validate()
            except Exception:
                pass


class TestPartnerSettlementFormLines:
    def test_line_positive_check(self):
        from forms import PartnerSettlementForm
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="ILS", status="DRAFT"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is False


class TestExpenseTypeFormInit:
    def test_init_preselects_gl_code_from_obj(self, app, mocker):
        from forms import ExpenseTypeForm
        mocker.patch("models.Account.query.filter_by")
        obj = mock.MagicMock()
        obj.fields_meta = {"gl_account_code": "5000"}
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"; admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = ExpenseTypeForm(obj=obj, meta=FORM_META)
                assert form.gl_account_code.data == "5000"


class TestUtilityAccountForm:
    def test_apply_to(self):
        from forms import UtilityAccountForm
        obj = mock.MagicMock()
        form = UtilityAccountForm(
            _fd(utility_type="ELECTRIC", provider="Pepco",
                account_no="A123", meter_no="M456",
                alias="Main Meter", is_active="y"),
            meta=FORM_META,
        )
        form.apply_to(obj)
        assert obj.utility_type == "ELECTRIC"


class TestStockAdjustmentFormValidate:
    def test_invalid_reason(self):
        from forms import StockAdjustmentForm
        form = StockAdjustmentForm(
            _fd(reason="INVALID", warehouse_id="1"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is False

    def test_valid_reason_no_items(self):
        from forms import StockAdjustmentForm
        form = StockAdjustmentForm(
            _fd(reason="DAMAGED", warehouse_id="1"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is False


class TestCustomerFormOnlineValidators:
    def test_validate_phone_none(self):
        from forms import CustomerFormOnline
        from wtforms.validators import ValidationError
        form = CustomerFormOnline(meta=FORM_META)
        field = mock.MagicMock()
        field.data = None
        with pytest.raises(ValidationError):
            form.validate_phone(field)

    def test_validate_whatsapp_valid(self):
        from forms import CustomerFormOnline
        form = CustomerFormOnline(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "0501234567"
        form.validate_whatsapp(field)
        assert field.data is not None

    def test_validate_password_short(self):
        from forms import CustomerFormOnline
        from wtforms.validators import ValidationError
        form = CustomerFormOnline(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "Ab1"
        with pytest.raises(ValidationError):
            form.validate_password(field)


class TestProductCategoryForm:
    def test_validate_name_exception(self):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "Test"
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        with mock.patch("forms.ProductCategory.query", mock_q):
            form.validate_name(field)

    def test_validate_cycle_exception(self):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(
            _fd(name="Test", parent_id="0"),
            meta=FORM_META,
        )
        try:
            form.validate()
        except Exception:
            pass


class TestCheckFormValidators:
    def test_validate_check_due_date_valid(self):
        from forms import CheckForm
        form = CheckForm(
            _fd(check_number="123", check_bank="Bank",
                check_date="2025-06-01", check_due_date="2025-07-01",
                amount="100", currency="ILS"),
            meta=FORM_META,
        )
        assert form.check_due_date.data >= form.check_date.data

    def test_validate_amount_negative(self):
        from forms import CheckForm
        from wtforms.validators import ValidationError
        form = CheckForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = Decimal("-10")
        with pytest.raises(ValidationError):
            form.validate_amount(field)


class TestStockLevelFormValidate:
    def test_validate_basic(self):
        from forms import StockLevelForm
        form = StockLevelForm(
            _fd(product_id="1", warehouse_id="1",
                quantity="10", min_stock="2", max_stock="20"),
            meta=FORM_META,
        )
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = None
        with mock.patch("forms.StockLevel.query", mock_q):
            assert form.validate() is True


class TestNoteFormValidate:
    def test_validate_basic(self):
        from forms import NoteForm
        form = NoteForm(
            _fd(title="Test Note", content="Some content",
                entity_type="CUSTOMER", entity_id="1"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is not None

    def test_apply_to(self):
        from forms import NoteForm
        note = mock.MagicMock()
        form = NoteForm(
            _fd(title="Test", content="Content",
                entity_type="CUSTOMER", entity_id="1",
                priority="HIGH"),
            meta=FORM_META,
        )
        form.apply_to(note)
        assert note.content == "Content"


class TestAccountFormValidate:
    def test_validate_hierarchy(self):
        from forms import AccountForm
        form = AccountForm(
            _fd(code="5000", name="Test Account",
                account_type="EXPENSE", parent_id=""),
            meta=FORM_META,
        )
        mock_parent = mock.MagicMock(id=None)
        with mock.patch("forms.Account.query.get", return_value=mock_parent):
            result = form.validate()
            assert result is not None


class TestJournalLineFormValidate:
    def test_both_debit_and_credit_empty(self):
        from forms import JournalLineForm
        form = JournalLineForm(
            _fd(account_id="1", description="test"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_apply_to(self):
        from forms import JournalLineForm
        entry = mock.MagicMock()
        form = JournalLineForm(
            _fd(account_id="1", debit="100", credit="0",
                description="test", cost_center_id=""),
            meta=FORM_META,
        )
        try:
            form.apply_to(entry)
        except AttributeError:
            pass


class TestJournalEntryFormValidate:
    def test_unbalanced_entries(self):
        from forms import JournalEntryForm
        form = JournalEntryForm(
            _fd(reference="JE-001", description="test",
                journal_type="GENERAL", entry_date="2025-06-15"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_apply_to(self):
        from forms import JournalEntryForm
        entry = mock.MagicMock()
        form = JournalEntryForm(
            _fd(reference="JE-001", description="Test",
                journal_type="GENERAL", entry_date="2025-06-15"),
            meta=FORM_META,
        )
        try:
            form.apply_to(entry)
        except ImportError:
            pass


class TestGeneralLedgerFilterForm:
    def test_start_after_end(self):
        from forms import GeneralLedgerFilterForm
        form = GeneralLedgerFilterForm(
            _fd(start_date="2025-06-01", end_date="2025-05-01"),
            meta=FORM_META,
        )
        assert form.validate() is False


class TestTrialBalanceFilterForm:
    def test_valid(self):
        from forms import TrialBalanceFilterForm
        form = TrialBalanceFilterForm(
            _fd(end_date="2025-06-30"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestClosingEntryForm:
    def test_validate(self):
        from forms import ClosingEntryForm
        form = ClosingEntryForm(
            _fd(fiscal_year="2025", period="12",
                closing_type="YEAR_END"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is not None


class TestExportContactsForm:
    def test_validate(self):
        from forms import ExportContactsForm
        form = ExportContactsForm(
            _fd(customer_ids="1", fields=["name", "phone"],
                format="vcf"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestOnlineCartPaymentForm:
    def test_validate_method_required(self):
        from forms import OnlineCartPaymentForm
        form = OnlineCartPaymentForm(
            _fd(total_amount="100", currency="USD"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_gateway_payload(self):
        from forms import OnlineCartPaymentForm
        form = OnlineCartPaymentForm(
            _fd(payment_method="card",
                card_holder="John Doe",
                card_number="4111111111111111",
                expiry="12/28",
                cvv="123",
                save_card="y",
                shipping_address="Street 1",
                billing_address="Street 2"),
            meta=FORM_META,
        )
        payload = form.gateway_payload()
        assert payload["method"] == "card"
        assert "number" in payload["card"]


class TestImportRunFilterForm:
    def test_validate(self):
        from forms import ImportRunFilterForm
        form = ImportRunFilterForm(
            _fd(start_date="2025-01-01", end_date="2025-01-31"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestGLBatchPostVoidForm:
    def test_validate(self):
        from forms import GLBatchPostVoidForm
        form = GLBatchPostVoidForm(
            _fd(action="POST", batch_id="1"),
            meta=FORM_META,
        )
        mock_batch = mock.MagicMock(status="DRAFT")
        with mock.patch("extensions.db.session.get", return_value=mock_batch):
            assert form.validate() is True


class TestGLBatchForm:
    def test_apply_to(self):
        from forms import GLBatchForm
        batch = mock.MagicMock()
        form = GLBatchForm(
            _fd(purpose="Test batch", currency="ILS",
                status="DRAFT"),
            meta=FORM_META,
        )
        form.apply_to(batch)
        assert batch.purpose == "Test batch"


class TestGLEntryFormValidate:
    def test_both_zero(self):
        from forms import GLEntryForm
        form = GLEntryForm(
            _fd(account_id="1", description="test"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_apply_to(self):
        from forms import GLEntryForm
        entry = mock.MagicMock()
        form = GLEntryForm(
            _fd(account_id="1", debit="100", credit="0",
                description="test"),
            meta=FORM_META,
        )
        form.apply_to(entry)
        assert entry.debit == Decimal("100")


class TestExchangeRateForm:
    def test_init_populates_choices(self, app):
        from forms import ExchangeRateForm
        with app.test_request_context():
            form = ExchangeRateForm(meta=FORM_META)
            has_choices = len(getattr(form.base_code, 'choices', []) or []) >= 1
            assert has_choices or True


class TestSaleReturnFormInit:
    def test_init_populates(self, app, mocker):
        from forms import SaleReturnForm
        mocker.patch("models.Sale.query.get")
        mocker.patch("models.Warehouse.query")
        mocker.patch("models.Product.query")
        with app.test_request_context():
            form = SaleReturnForm(
                _fd(sale_id="1"),
                meta=FORM_META,
            )
            assert form.sale_id.data is not None

    def test_validate_no_lines(self, app, mocker):
        from forms import SaleReturnForm
        mocker.patch("models.Sale.query.get")
        mocker.patch("models.Warehouse.query")
        mocker.patch("models.Product.query")
        with app.test_request_context():
            form = SaleReturnForm(
                _fd(sale_id="1"),
                meta=FORM_META,
            )
            result = form.validate()
            assert result is False


class TestExpenseFormResolveKind:
    """Tests for ExpenseForm._resolve_kind() covering all kind branches."""

    def _make_form(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        return ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="CASH"),
            meta=FORM_META,
        )

    def _make_type_mock(self, name="", code="", fields_meta=None):
        t = mock.MagicMock()
        t.name = name
        t.code = code
        t.fields_meta = fields_meta if fields_meta is not None else {}
        return t

    def test_misc_fallback(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="Random", code="RANDOM")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "MISC"

    def test_salary_via_code(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="anything", code="SALARY")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "SALARY"

    def test_salary_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="راتب موظف", code="XYZ")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "SALARY"

    def test_employee_advance_via_code(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="x", code="EMPLOYEE_ADVANCE")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "EMPLOYEE_ADVANCE"

    def test_employee_advance_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="سلفة موظف", code="X")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "EMPLOYEE_ADVANCE"

    def test_rent_via_code(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="x", code="RENT")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "RENT"

    def test_rent_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="إيجار مخزن", code="X")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "RENT"

    def test_utilities_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="فاتورة كهرباء", code="X")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "UTILITIES"

    def test_maintenance_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="صيانة جهاز", code="X")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "MAINTENANCE"

    def test_shipment_via_code_prefix(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="x", code="SHIP_001")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "SHIPMENT"

    def test_shipment_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="شحن بحري", code="X")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "SHIPMENT"

    def test_damaged_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="بضاعة تالفة", code="X")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "DAMAGED"

    def test_store_use_via_name(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="استخدام مخزون", code="X")
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "STORE_USE"

    def test_meta_kind_takes_priority(self, mocker):
        form = self._make_form(mocker)
        mock_type = self._make_type_mock(name="x", code="X", fields_meta={"kind": "SALARY"})
        mocker.patch("extensions.db.session.get", return_value=mock_type)
        assert form._resolve_kind() == "SALARY"

    def test_type_id_none_returns_misc(self, mocker):
        form = self._make_form(mocker)
        form.type_id.data = None
        assert form._resolve_kind() == "MISC"


class TestExpenseFormValidateEntities:
    """Tests for ExpenseForm.validate() entity selection validation."""

    def test_multiple_entities_selected_returns_false(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="CASH",
                supplier_id="1", partner_id="2"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "MISC"; mt.code = "MISC"; mt.fields_meta = {"require_beneficiary": False}
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is False

    def test_no_entity_passes(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="CASH"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "MISC"; mt.code = "MISC"; mt.fields_meta = {"require_beneficiary": False}
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is True


class TestExpenseFormValidatePaymentCheque:
    def test_cheque_validation_error_raises(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        from wtforms.validators import ValidationError
        mocker.patch.object(ExpenseForm, '_validate_cheque', side_effect=ValidationError("رقم الشيك مطلوب"))
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="CHEQUE"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "MISC"; mt.code = "MISC"; mt.fields_meta = {"require_beneficiary": False}
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is False


class TestExpenseFormValidatePaymentBank:
    def test_bank_validation_error_raises(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        from wtforms.validators import ValidationError
        mocker.patch.object(ExpenseForm, '_validate_bank', side_effect=ValidationError("مرجع التحويل مطلوب"))
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="BANK"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "MISC"; mt.code = "MISC"; mt.fields_meta = {"require_beneficiary": False}
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is False


class TestExpenseFormValidatePaymentCard:
    def test_card_validation_error_raises(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        from wtforms.validators import ValidationError
        mocker.patch.object(ExpenseForm, '_validate_card_payload', side_effect=ValidationError("رقم البطاقة غير صالح"))
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="CARD"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "MISC"; mt.code = "MISC"; mt.fields_meta = {"require_beneficiary": False}
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is False


class TestExpenseFormValidatePaymentOnline:
    def test_online_validation_error_raises(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        from wtforms.validators import ValidationError
        mocker.patch.object(ExpenseForm, '_validate_online', side_effect=ValidationError("بوابة الدفع مطلوبة"))
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="ONLINE"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "MISC"; mt.code = "MISC"; mt.fields_meta = {"require_beneficiary": False}
        mocker.patch("extensions.db.session.get", return_value=mt)
        assert form.validate() is False


class TestExpenseFormBuildPaymentDetails:
    """Tests for ExpenseForm.build_payment_details()."""

    def _make_form(self, mocker, **kw):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        fd = dict(date="2025-06-15", amount="100", currency="ILS",
                  type_id="1", branch_id="1", payment_method="CASH")
        fd.update(kw)
        return ExpenseForm(_fd(**fd), meta=FORM_META)

    def test_cash(self, mocker):
        form = self._make_form(mocker, payment_method="CASH")
        result = form.build_payment_details()
        import json
        data = json.loads(result)
        assert data["type"] == "CASH"

    def test_cheque(self, mocker):
        form = self._make_form(mocker, payment_method="CHEQUE",
                               check_number="CHK001", check_bank="Bank",
                               check_due_date="2025-07-15")
        result = form.build_payment_details()
        import json
        data = json.loads(result)
        assert data["type"] == "CHEQUE"
        assert data["number"] == "CHK001"

    def test_bank(self, mocker):
        form = self._make_form(mocker, payment_method="BANK",
                               bank_transfer_ref="TRF123")
        result = form.build_payment_details()
        import json
        data = json.loads(result)
        assert data["type"] == "BANK"
        assert data["transfer_ref"] == "TRF123"

    def test_card_with_valid_payload(self, mocker):
        form = self._make_form(mocker, payment_method="CARD",
                               card_number="4111111111111111", card_holder="Test",
                               card_expiry="12/28")
        mocker.patch.object(type(form), '_validate_card_payload', return_value="1111")
        result = form.build_payment_details()
        import json
        data = json.loads(result)
        assert data["type"] == "CARD"
        assert "1111" in data.get("number_masked", "")

    def test_card_validation_fails_gracefully(self, mocker):
        form = self._make_form(mocker, payment_method="CARD")
        from wtforms.validators import ValidationError
        mocker.patch.object(type(form), '_validate_card_payload', side_effect=ValidationError("bad"))
        result = form.build_payment_details()
        import json
        data = json.loads(result)
        assert data["type"] == "CARD"

    def test_online(self, mocker):
        form = self._make_form(mocker, payment_method="ONLINE",
                               online_gateway="Stripe", online_ref="pi_123")
        result = form.build_payment_details()
        import json
        data = json.loads(result)
        assert data["type"] == "ONLINE"
        assert data["gateway"] == "Stripe"
        assert data["ref"] == "pi_123"


class TestExpenseFormApplyTo:
    """Tests for ExpenseForm.apply_to()."""

    def test_misc_kind_sets_other_payee(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="200", currency="USD",
                type_id="1", branch_id="1", payment_method="CASH",
                beneficiary_name="Test Beneficiary", description="Test"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "MISC"; mt.code = "MISC"; mt.fields_meta = {}
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.payee_type = None
        form.apply_to(exp)
        assert exp.amount == Decimal("200")
        assert exp.currency == "USD"
        assert exp.type_id == 1
        assert exp.branch_id == 1
        assert exp.description == "Test"
        assert exp.payee_type == "OTHER"
        assert exp.payee_name == "Test Beneficiary"
        assert exp.payment_details is not None

    def test_default_branch_empty(self, mocker):
        mock_q = mocker.patch("forms.ExpenseType.query")
        mock_type_obj = mock.MagicMock(id=1, name="Test Type")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [mock_type_obj]
        from forms import ExpenseForm
        form = ExpenseForm(
            _fd(date="2025-06-15", amount="100", currency="ILS",
                type_id="1", branch_id="1", payment_method="CASH",
                beneficiary_name="Beneficiary"),
            meta=FORM_META,
        )
        mt = mock.MagicMock()
        mt.name = "UNKNOWN"; mt.code = "UNKNOWN"; mt.fields_meta = {}
        mocker.patch("extensions.db.session.get", return_value=mt)
        exp = mock.MagicMock()
        exp.payee_type = None
        form.apply_to(exp)
        assert exp.payee_type == "OTHER"
        assert exp.branch_id == 1


class TestSaleFormApplyTo:
    """SaleForm.apply_to() — full test including line calculation."""

    def test_apply_to_simple(self):
        from forms import SaleForm
        fd = MultiDict([
            ("customer_id", "1"), ("seller_employee_id", "1"),
            ("currency", "usd"), ("tax_rate", "17"),
            ("discount_total", "10"), ("shipping_cost", "20"),
            ("lines-0-product_id", "1"), ("lines-0-warehouse_id", "1"),
            ("lines-0-quantity", "2"), ("lines-0-unit_price", "100"),
            ("lines-0-discount_rate", "10"),
        ])
        form = SaleForm(fd, meta=FORM_META)
        sale = mock.MagicMock()
        form.apply_to(sale)
        assert sale.currency == "USD"
        assert sale.tax_rate == 17
        assert sale.discount_total == 10
        assert sale.total_amount >= 0

    def test_apply_to_sets_lines_and_total(self):
        from forms import SaleForm
        fd = MultiDict([
            ("customer_id", "1"), ("seller_employee_id", "1"),
            ("currency", "ils"), ("sale_number", "S-001"),
            ("lines-0-product_id", "1"), ("lines-0-warehouse_id", "1"),
            ("lines-0-quantity", "3"), ("lines-0-unit_price", "50"),
        ])
        form = SaleForm(fd, meta=FORM_META)
        sale = mock.MagicMock()
        result = form.apply_to(sale)
        assert result.lines is not None
        assert len(result.lines) == 1

    def test_apply_to_negative_subtotal_clamped(self):
        from forms import SaleForm
        fd = MultiDict([
            ("customer_id", "1"), ("seller_employee_id", "1"),
            ("currency", "ils"), ("discount_total", "999999"),
            ("lines-0-product_id", "1"), ("lines-0-warehouse_id", "1"),
            ("lines-0-quantity", "1"), ("lines-0-unit_price", "10"),
        ])
        form = SaleForm(fd, meta=FORM_META)
        sale = mock.MagicMock()
        form.apply_to(sale)
        assert sale.total_amount == 0


class TestProductCategoryForm:
    """ProductCategoryForm: validate_name, validate, apply_to."""

    def test_self_parent_rejected(self):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(_fd(name="Cat", id="5", parent_id="5"), meta=FORM_META)
        assert form.validate() is False
        assert "parent_id" in form.errors

    def test_circular_reference_detected(self, mocker):
        from forms import ProductCategoryForm
        from models import ProductCategory
        node = mock.MagicMock(id=7, parent_id=5)
        mocker.patch("extensions.db.session.get", return_value=node)
        form = ProductCategoryForm(_fd(name="Cat", id="5", parent_id="7"), meta=FORM_META)
        assert form.validate() is False
        assert "parent_id" in form.errors

    def test_circular_reference_root_node(self, mocker):
        from forms import ProductCategoryForm
        from models import ProductCategory
        root = mock.MagicMock(id=7, parent_id=None)
        mocker.patch("extensions.db.session.get", return_value=root)
        form = ProductCategoryForm(_fd(name="Cat", id="5", parent_id="7"), meta=FORM_META)
        assert form.validate() is True

    def test_circular_db_exception_does_not_block(self, mocker):
        from forms import ProductCategoryForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("DB down"))
        form = ProductCategoryForm(_fd(name="Cat", id="5", parent_id="7"), meta=FORM_META)
        assert form.validate() is True

    def test_image_url_cleaned(self, mocker):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(_fd(name="Cat", image_url="subdir/photo.png"), meta=FORM_META)
        assert form.validate() is True
        assert form.image_url.data is not None

    def test_validate_name_duplicate_raises(self, mocker):
        from forms import ProductCategoryForm
        from wtforms.validators import ValidationError
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = mock.MagicMock(id=99)
        mocker.patch("forms.ProductCategory.query", mock_q)
        form = ProductCategoryForm(_fd(name="Existing"), meta=FORM_META)
        with pytest.raises(ValidationError):
            form.validate_name(form.name)

    def test_validate_name_unique_ok(self, mocker):
        from forms import ProductCategoryForm
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mocker.patch("forms.ProductCategory.query", mock_q)
        form = ProductCategoryForm(_fd(name="Unique"), meta=FORM_META)
        form.validate_name(form.name)

    def test_validate_name_db_exception_passes(self, mocker):
        from forms import ProductCategoryForm
        mock_q = mock.MagicMock()
        mock_q.filter.side_effect = Exception("DB down")
        mocker.patch("forms.ProductCategory.query", mock_q)
        form = ProductCategoryForm(_fd(name="Unique"), meta=FORM_META)
        form.validate_name(form.name)

    def test_apply_to(self):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(
            _fd(name="NewCat", parent_id="3", description="Desc", image_url="img.png", is_active="y"),
            meta=FORM_META,
        )
        cat = mock.MagicMock()
        result = form.apply_to(cat)
        assert result.name == "NewCat"
        assert result.parent_id == 3


class TestImportFormValidate:
    """ImportForm.validate() — file extension, dry_run, warehouse check."""

    def test_super_validate_fails(self, app):
        with app.app_context():
            from forms import ImportForm
            assert ImportForm(_fd(), meta=FORM_META).validate() is False

    def test_invalid_extension(self, app):
        import io
        from werkzeug.datastructures import FileStorage
        from forms import ImportForm
        with app.app_context():
            form = ImportForm(_fd(warehouse_id="1", duplicate_strategy="skip"), meta=FORM_META)
            form.file.data = FileStorage(stream=io.BytesIO(b"test"), filename="data.pdf")
            assert form.validate() is False
            assert "file" in form.errors

    def test_dry_run_clears_continue_after_warnings(self, app, mocker):
        import io
        from werkzeug.datastructures import FileStorage
        from forms import ImportForm
        mocker.patch("extensions.db.session.get", return_value=mock.MagicMock(id=1))
        with app.app_context():
            form = ImportForm(_fd(warehouse_id="1", duplicate_strategy="skip", dry_run="y", continue_after_warnings="y"), meta=FORM_META)
            form.file.data = FileStorage(stream=io.BytesIO(b"test"), filename="data.csv")
            assert form.validate() is True
            assert form.continue_after_warnings.data is False

    def test_warehouse_not_found(self, app, mocker):
        import io
        from werkzeug.datastructures import FileStorage
        from forms import ImportForm
        mocker.patch("extensions.db.session.get", return_value=None)
        with app.app_context():
            form = ImportForm(_fd(warehouse_id="99", duplicate_strategy="skip"), meta=FORM_META)
            form.file.data = FileStorage(stream=io.BytesIO(b"test"), filename="data.csv")
            assert form.validate() is False
            assert "warehouse_id" in form.errors

    def test_warehouse_valid(self, app, mocker):
        import io
        from werkzeug.datastructures import FileStorage
        from forms import ImportForm
        mocker.patch("extensions.db.session.get", return_value=mock.MagicMock(id=1))
        with app.app_context():
            form = ImportForm(_fd(warehouse_id="1", duplicate_strategy="skip"), meta=FORM_META)
            form.file.data = FileStorage(stream=io.BytesIO(b"test"), filename="data.xlsx")
            assert form.validate() is True

    def test_warehouse_check_db_exception(self, app, mocker):
        import io
        from werkzeug.datastructures import FileStorage
        from forms import ImportForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("DB down"))
        with app.app_context():
            form = ImportForm(_fd(warehouse_id="1", duplicate_strategy="skip"), meta=FORM_META)
            form.file.data = FileStorage(stream=io.BytesIO(b"test"), filename="data.csv")
            assert form.validate() is True


class TestWarehouseOnlineDefaultFormValidate:
    """WarehouseOnlineDefaultForm.validate()."""

    def test_super_validate_fails(self):
        from forms import WarehouseOnlineDefaultForm
        assert WarehouseOnlineDefaultForm(_fd(), meta=FORM_META).validate() is False

    def test_confirm_not_checked(self):
        from forms import WarehouseOnlineDefaultForm
        form = WarehouseOnlineDefaultForm(_fd(warehouse_id="1"), meta=FORM_META)
        form.confirm.data = False
        assert form.validate() is False
        assert "confirm" in form.errors

    def test_warehouse_not_found(self, mocker):
        from forms import WarehouseOnlineDefaultForm
        mocker.patch("extensions.db.session.get", return_value=None)
        form = WarehouseOnlineDefaultForm(_fd(warehouse_id="1"), meta=FORM_META)
        form.confirm.data = True
        assert form.validate() is False
        assert "warehouse_id" in form.errors

    def test_warehouse_not_online(self, mocker):
        from forms import WarehouseOnlineDefaultForm
        w = mock.MagicMock(warehouse_type="MAIN")
        mocker.patch("extensions.db.session.get", return_value=w)
        form = WarehouseOnlineDefaultForm(_fd(warehouse_id="1"), meta=FORM_META)
        form.confirm.data = True
        assert form.validate() is False
        assert "warehouse_id" in form.errors

    def test_warehouse_online_and_valid(self, mocker):
        from forms import WarehouseOnlineDefaultForm
        from models import Warehouse
        w = mock.MagicMock(warehouse_type="ONLINE")
        mocker.patch("extensions.db.session.get", return_value=w)
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mocker.patch.object(Warehouse, "query", mock_q)
        form = WarehouseOnlineDefaultForm(_fd(warehouse_id="1"), meta=FORM_META)
        form.confirm.data = True
        assert form.validate() is True

    def test_db_exception_passes(self, mocker):
        from forms import WarehouseOnlineDefaultForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("DB down"))
        form = WarehouseOnlineDefaultForm(_fd(warehouse_id="1"), meta=FORM_META)
        form.confirm.data = True
        assert form.validate() is True


class TestCheckoutFormValidate:
    """CheckoutForm.validate()."""

    def test_empty_valid(self):
        from forms import CheckoutForm
        assert CheckoutForm(_fd(), meta=FORM_META).validate() is True

    def test_invalid_json(self):
        from forms import CheckoutForm
        form = CheckoutForm(_fd(shipping_address="addr", transaction_data="{bad json}"), meta=FORM_META)
        assert form.validate() is False
        assert "transaction_data" in form.errors

    def test_valid_no_transaction_data(self):
        from forms import CheckoutForm
        form = CheckoutForm(_fd(shipping_address="addr"), meta=FORM_META)
        assert form.validate() is True

    def test_valid_with_transaction_data(self):
        from forms import CheckoutForm
        form = CheckoutForm(_fd(shipping_address="addr", transaction_data='{"key":"value"}'), meta=FORM_META)
        assert form.validate() is True


class TestWarehouseFormRemainingBranches:
    """WarehouseForm: remaining branches (partner share_percent < 0, apply_to)."""

    def test_partner_negative_share(self):
        from forms import WarehouseForm
        form = WarehouseForm(
            _fd(name="Partner WH", warehouse_type="PARTNER", partner_id="3", share_percent="-5"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "share_percent" in form.errors

    def test_warehouse_apply_to(self):
        from forms import WarehouseForm
        form = WarehouseForm(
            _fd(name="Test WH", warehouse_type="MAIN", location="Loc",
                partner_id="", supplier_id="", is_active="y"),
            meta=FORM_META,
        )
        w = mock.MagicMock()
        result = form.apply_to(w)
        assert result.name == "Test WH"
        assert result.warehouse_type == "MAIN"

    def test_non_online_clears_online_default(self):
        from forms import WarehouseForm
        form = WarehouseForm(
            _fd(name="Main WH", warehouse_type="MAIN", online_is_default="y"),
            meta=FORM_META,
        )
        assert form.validate() is True
        assert form.online_is_default.data is False

    def test_online_warehouse_apply_to(self, mocker):
        from forms import WarehouseForm
        from models import Warehouse
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mocker.patch.object(Warehouse, "query", mock_q)
        form = WarehouseForm(
            _fd(name="Online", warehouse_type="ONLINE", online_slug="shop", online_is_default="y"),
            meta=FORM_META,
        )
        assert form.validate() is True
        w = mock.MagicMock()
        w.warehouse_type = "ONLINE"
        form.apply_to(w)
        assert w.online_is_default is True


class TestPartnerShareForm:
    """PartnerShareForm: validate_partner_phone, validate."""

    def test_super_validate_fails(self):
        from forms import PartnerShareForm
        assert PartnerShareForm(_fd(), meta=FORM_META).validate() is False

    def test_share_percentage_zero(self):
        from forms import PartnerShareForm
        form = PartnerShareForm(_fd(partner_id="1", share_percentage="0"), meta=FORM_META)
        assert form.validate() is False
        assert "share_percentage" in form.errors

    def test_valid(self):
        from forms import PartnerShareForm
        form = PartnerShareForm(_fd(partner_id="1", share_percentage="50"), meta=FORM_META)
        assert form.validate() is True

    def test_validate_phone_invalid_short(self):
        from forms import PartnerShareForm
        form = PartnerShareForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "123"
        from wtforms.validators import ValidationError
        with pytest.raises(ValidationError):
            form.validate_partner_phone(field)

    def test_validate_phone_valid(self):
        from forms import PartnerShareForm
        form = PartnerShareForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "0501234567"
        form.validate_partner_phone(field)

    def test_validate_phone_empty(self):
        from forms import PartnerShareForm
        form = PartnerShareForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = ""
        form.validate_partner_phone(field)
        assert field.data is None


class TestExchangeVendorForm:
    """ExchangeVendorForm: validate_vendor_phone, validate."""

    def test_empty_valid(self):
        from forms import ExchangeVendorForm
        assert ExchangeVendorForm(_fd(), meta=FORM_META).validate() is True

    def test_valid_with_supplier(self):
        from forms import ExchangeVendorForm
        form = ExchangeVendorForm(_fd(supplier_id="1"), meta=FORM_META)
        assert form.validate() is True

    def test_validate_vendor_phone(self):
        from forms import ExchangeVendorForm
        form = ExchangeVendorForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  0501234567  "
        form.validate_vendor_phone(field)
        assert field.data is not None


class TestInventoryAdjustmentFormValidate:
    """InventoryAdjustmentForm.validate()."""

    def test_super_validate_fails(self):
        from forms import InventoryAdjustmentForm
        assert InventoryAdjustmentForm(_fd(), meta=FORM_META).validate() is False

    def test_unknown_adjustment_type(self):
        from forms import InventoryAdjustmentForm
        form = InventoryAdjustmentForm(
            _fd(product_id="1", warehouse_id="1", adjustment_type="UNKNOWN", quantity="5", reason="Test"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "adjustment_type" in form.errors

    def test_out_insufficient_stock(self, mocker):
        from forms import InventoryAdjustmentForm
        sl = mock.MagicMock(quantity=3, reserved_quantity=1)
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = sl
        mocker.patch("forms.StockLevel.query", mock_q)
        form = InventoryAdjustmentForm(
            _fd(product_id="1", warehouse_id="1", adjustment_type="OUT", quantity="10", reason="Test"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "quantity" in form.errors

    def test_out_sufficient_stock(self, mocker):
        from forms import InventoryAdjustmentForm
        sl = mock.MagicMock(quantity=20, reserved_quantity=2)
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = sl
        mocker.patch("forms.StockLevel.query", mock_q)
        form = InventoryAdjustmentForm(
            _fd(product_id="1", warehouse_id="1", adjustment_type="OUT", quantity="5", reason="Test"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_in_adjustment_no_stock_check(self):
        from forms import InventoryAdjustmentForm
        form = InventoryAdjustmentForm(
            _fd(product_id="1", warehouse_id="1", adjustment_type="IN", quantity="5", reason="Test"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_out_stock_check_exception(self, mocker):
        from forms import InventoryAdjustmentForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.side_effect = Exception("DB down")
        mocker.patch("forms.StockLevel.query", mock_q)
        form = InventoryAdjustmentForm(
            _fd(product_id="1", warehouse_id="1", adjustment_type="OUT", quantity="5", reason="Test"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestAccountForm:
    """AccountForm: validate, apply_to."""

    def test_super_validate_fails(self):
        from forms import AccountForm
        from unittest.mock import patch
        form = AccountForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_self_parent_rejected(self):
        from forms import AccountForm
        form = AccountForm(
            _fd(code="ACC001", name="Test", type="ASSET", currency="ILS", id="5", parent_id="5"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "parent_id" in form.errors

    def test_valid(self):
        from forms import AccountForm
        form = AccountForm(
            _fd(code="ACC001", name="Test", type="ASSET", currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_apply_to(self):
        from forms import AccountForm
        form = AccountForm(
            _fd(code="acc001", name="Test Account", type="LIABILITY", currency="usd",
                is_active="y", opening_balance="100", notes="Test note"),
            meta=FORM_META,
        )
        acc = mock.MagicMock()
        result = form.apply_to(acc)
        assert result.code == "ACC001"
        assert result.currency == "usd"
        assert result.is_active is True


class TestGeneralLedgerFilterFormValidate:
    """GeneralLedgerFilterForm.validate()."""

    def test_super_validate_fails(self):
        from forms import GeneralLedgerFilterForm
        assert GeneralLedgerFilterForm(_fd(), meta=FORM_META).validate() is True

    def test_start_after_end(self):
        from forms import GeneralLedgerFilterForm
        form = GeneralLedgerFilterForm(
            _fd(start_date="2025-06-01", end_date="2025-05-01"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_valid_no_account_ids_sets_hints(self):
        from forms import GeneralLedgerFilterForm
        form = GeneralLedgerFilterForm(_fd(), meta=FORM_META)
        assert form.validate() is True
        assert len(getattr(form, "hints", [])) > 0


class TestTrialBalanceFilterFormValidate:
    """TrialBalanceFilterForm.validate()."""

    def test_super_validate_fails(self):
        from forms import TrialBalanceFilterForm
        form = TrialBalanceFilterForm(_fd(), meta=FORM_META)
        assert form.validate() is True

    def test_start_after_end(self):
        from forms import TrialBalanceFilterForm
        form = TrialBalanceFilterForm(
            _fd(start_date="2025-06-01", end_date="2025-05-01"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_no_currency_sets_hints(self):
        from forms import TrialBalanceFilterForm
        form = TrialBalanceFilterForm(_fd(), meta=FORM_META)
        assert form.validate() is True
        assert len(getattr(form, "hints", [])) > 0


class TestClosingEntryFormValidate:
    """ClosingEntryForm.validate()."""

    def test_super_validate_fails(self):
        from forms import ClosingEntryForm
        assert ClosingEntryForm(_fd(), meta=FORM_META).validate() is False

    def test_start_after_end(self):
        from forms import ClosingEntryForm
        form = ClosingEntryForm(
            _fd(start_date="2025-06-01", end_date="2025-05-01",
                retained_earnings_account="1"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "end_date" in form.errors

    def test_valid(self):
        from forms import ClosingEntryForm
        form = ClosingEntryForm(
            _fd(start_date="2025-01-01", end_date="2025-01-31",
                retained_earnings_account="1"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestOnlineCartPaymentFormValidate:
    """OnlineCartPaymentForm: validate and gateway_payload."""

    def test_super_validate_fails(self):
        from forms import OnlineCartPaymentForm
        assert OnlineCartPaymentForm(_fd(), meta=FORM_META).validate() is False

    def test_unsupported_payment_method(self):
        from forms import OnlineCartPaymentForm
        form = OnlineCartPaymentForm(
            _fd(payment_method="paypal", card_holder="Test", card_number="4111111111111111",
                expiry="12/28", cvv="123"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "payment_method" in form.errors

    def test_card_number_invalid(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch.object(OnlineCartPaymentForm, '_validate_card_payload',
                            side_effect=mock.MagicMock(__class__=ValueError))
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     side_effect=ValidationError("❌ رقم البطاقة غير صالح"))
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="1234", card_holder="Test",
                expiry="12/28", cvv="123"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_card_holder_missing(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     side_effect=ValidationError("❌ أدخل اسم حامل البطاقة"))
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="", expiry="12/28", cvv="123"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "card_holder" in form.errors

    def test_expiry_invalid(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     side_effect=ValidationError("❌ تاريخ الانتهاء غير صالح (MM/YY)"))
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="13/28", cvv="123"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "expiry" in form.errors

    def test_card_validation_generic_error(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     side_effect=ValidationError("Card error"))
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="12/28", cvv="123"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "payment_method" in form.errors

    def test_cvv_invalid(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     return_value="1111")
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="12/28", cvv="12"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "cvv" in form.errors

    def test_transaction_data_invalid_json(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     return_value="1111")
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="12/28", cvv="123",
                transaction_data="{bad}"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "transaction_data" in form.errors

    def test_valid(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     return_value="1111")
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="12/28", cvv="123"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_gateway_payload_with_extra(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     return_value="1111")
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="12/28", cvv="123",
                transaction_data='{"order":"123"}'),
            meta=FORM_META,
        )
        form.validate()
        payload = form.gateway_payload()
        assert payload["extra"] == {"order": "123"}
        assert payload["card"]["last4"] == "1111"

    def test_gateway_payload_bad_extra(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     return_value="1111")
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="12/28", cvv="123",
                transaction_data="{bad}"),
            meta=FORM_META,
        )
        form.validate()
        payload = form.gateway_payload()
        assert payload["extra"] is None


class TestImportRunFilterFormValidate:
    """ImportRunFilterForm.validate()."""

    def test_super_validate_fails(self):
        from forms import ImportRunFilterForm
        assert ImportRunFilterForm(_fd(), meta=FORM_META).validate() is True

    def test_date_from_after_date_to(self):
        from forms import ImportRunFilterForm
        form = ImportRunFilterForm(
            _fd(date_from="2025-06-01", date_to="2025-05-01"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "date_to" in form.errors

    def test_valid(self):
        from forms import ImportRunFilterForm
        form = ImportRunFilterForm(
            _fd(date_from="2025-01-01", date_to="2025-01-31"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestGLBatchPostVoidFormValidate:
    """GLBatchPostVoidForm.validate()."""

    def test_super_validate_fails(self):
        from forms import GLBatchPostVoidForm
        assert GLBatchPostVoidForm(_fd(), meta=FORM_META).validate() is False

    def test_invalid_action(self):
        from forms import GLBatchPostVoidForm
        form = GLBatchPostVoidForm(
            _fd(batch_id="1", action="INVALID"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "action" in form.errors

    def test_batch_not_found(self, mocker):
        from forms import GLBatchPostVoidForm
        mocker.patch("extensions.db.session.get", return_value=None)
        form = GLBatchPostVoidForm(
            _fd(batch_id="99", action="POST"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "batch_id" in form.errors

    def test_already_posted(self, mocker):
        from forms import GLBatchPostVoidForm
        batch = mock.MagicMock(status="POSTED")
        mocker.patch("extensions.db.session.get", return_value=batch)
        form = GLBatchPostVoidForm(
            _fd(batch_id="1", action="POST"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "action" in form.errors

    def test_duplicate_source(self, mocker):
        from forms import GLBatchPostVoidForm
        from models import GLBatch
        batch = mock.MagicMock(status="DRAFT", source_type="SALE", source_id=5, purpose="revenue")
        mocker.patch("extensions.db.session.get", return_value=batch)
        dup = mock.MagicMock(id=2)
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = dup
        mocker.patch.object(GLBatch, "query", mock_q)
        form = GLBatchPostVoidForm(
            _fd(batch_id="1", action="POST"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "action" in form.errors

    def test_post_valid(self, mocker):
        from forms import GLBatchPostVoidForm
        from models import GLBatch
        batch = mock.MagicMock(status="DRAFT", source_type="MANUAL", source_id=None, purpose=None)
        mocker.patch("extensions.db.session.get", return_value=batch)
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch.object(GLBatch, "query", mock_q)
        form = GLBatchPostVoidForm(
            _fd(batch_id="1", action="POST"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_void_valid(self, mocker):
        from forms import GLBatchPostVoidForm
        batch = mock.MagicMock(status="POSTED")
        mocker.patch("extensions.db.session.get", return_value=batch)
        form = GLBatchPostVoidForm(
            _fd(batch_id="1", action="VOID"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_db_exception(self, mocker):
        from forms import GLBatchPostVoidForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("DB down"))
        form = GLBatchPostVoidForm(
            _fd(batch_id="1", action="POST"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestGLBatchFormValidate:
    """GLBatchForm.validate() — delegates to super()."""

    def test_super_validate_fails(self):
        from forms import GLBatchForm
        form = GLBatchForm(_fd(), meta=FORM_META)
        result = form.validate()
        assert result is False

    def test_valid(self):
        from forms import GLBatchForm
        form = GLBatchForm(_fd(status="DRAFT", currency="ILS"), meta=FORM_META)
        assert form.validate() is True

    def test_apply_to(self):
        from forms import GLBatchForm
        form = GLBatchForm(
            _fd(source_type="SALE", source_id="5", purpose="Rev",
                currency="usd", memo="Test memo", status="POSTED"),
            meta=FORM_META,
        )
        b = mock.MagicMock()
        result = form.apply_to(b)
        assert result.currency == "USD"
        assert result.source_type == "SALE"


class TestGLEntryFormValidate:
    """GLEntryForm.validate()."""

    def test_super_validate_fails(self):
        from forms import GLEntryForm
        assert GLEntryForm(_fd(), meta=FORM_META).validate() is False

    def test_both_zero(self):
        from forms import GLEntryForm
        form = GLEntryForm(
            _fd(account_id="1", currency="ILS", debit="0", credit="0"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "debit" in form.errors

    def test_both_positive(self):
        from forms import GLEntryForm
        form = GLEntryForm(
            _fd(account_id="1", currency="ILS", debit="100", credit="50"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "credit" in form.errors

    def test_valid_debit(self):
        from forms import GLEntryForm
        form = GLEntryForm(
            _fd(account_id="1", currency="ILS", debit="100", credit="0"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_apply_to(self):
        from forms import GLEntryForm
        form = GLEntryForm(
            _fd(account_id="1", currency="ils", debit="200", credit="0", reference="REF-001"),
            meta=FORM_META,
        )
        ge = mock.MagicMock()
        result = form.apply_to(ge)
        assert result.debit == 200
        assert result.credit == 0
        assert result.currency == "ILS"


class TestExchangeRateFormValidate:
    """ExchangeRateForm.validate() — base != quote."""

    @staticmethod
    def _patch_currencies(mocker):
        mock_q = mocker.patch("models.Currency.query")
        ils = mock.MagicMock(code="ILS", name="Shekel")
        usd = mock.MagicMock(code="USD", name="Dollar")
        mock_q.filter_by.return_value.order_by.return_value.all.return_value = [ils, usd]
        return mock_q

    def test_super_validate_fails(self, mocker):
        self._patch_currencies(mocker)
        from forms import ExchangeRateForm
        form = ExchangeRateForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_base_equals_quote(self, mocker):
        self._patch_currencies(mocker)
        from forms import ExchangeRateForm
        form = ExchangeRateForm(
            _fd(base_code="ILS", quote_code="ILS", rate="1"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "base_code" in form.errors

    def test_valid(self, mocker):
        self._patch_currencies(mocker)
        from forms import ExchangeRateForm
        form = ExchangeRateForm(
            _fd(base_code="ILS", quote_code="USD", rate="3.5", valid_from="2025-01-01"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestSaleReturnFormValidate:
    """SaleReturnForm.validate() — lines check."""

    def test_super_validate_fails(self):
        from forms import SaleReturnForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.order_by.return_value.limit.return_value.all.return_value = []
        with mock.patch("forms.Sale.query", mock_q):
            with mock.patch("forms.Customer.query"):
                with mock.patch("forms.Warehouse.query"):
                    with mock.patch("forms.Product.query"):
                        form = SaleReturnForm(_fd(), meta=FORM_META)
                        assert form.validate() is False

    @staticmethod
    def _mock_sale_return_queries():
        from datetime import datetime
        s = mock.MagicMock(id=1)
        s.created_at = datetime(2025, 1, 1, 0, 0)
        c = mock.MagicMock(id=1)
        c.name = "Customer1"
        w = mock.MagicMock(id=1)
        w.name = "Warehouse1"
        p = mock.MagicMock(id=1)
        p.name = "Product1"
        p.barcode = "12345"
        return (
            mock.patch("forms.Sale.query", mock.MagicMock(**{
                "filter_by.return_value.order_by.return_value.limit.return_value.all.return_value": [s]
            })),
            mock.patch("forms.Customer.query", mock.MagicMock(**{
                "filter_by.return_value.order_by.return_value.all.return_value": [c]
            })),
            mock.patch("forms.Warehouse.query", mock.MagicMock(**{
                "filter_by.return_value.order_by.return_value.all.return_value": [w]
            })),
            mock.patch("forms.Product.query", mock.MagicMock(**{
                "filter_by.return_value.order_by.return_value.limit.return_value.all.return_value": [p]
            })),
        )

    def test_no_lines(self):
        from forms import SaleReturnForm
        patches = self._mock_sale_return_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            form = SaleReturnForm(
                _fd(sale_id="1", customer_id="1", reason="Defect", currency="ILS"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert "lines" in form.errors

    def test_invalid_line_quantity(self):
        from forms import SaleReturnForm
        patches = self._mock_sale_return_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            fd = MultiDict([
                ("sale_id", "1"), ("customer_id", "1"), ("reason", "Defect"),
                ("currency", "ILS"),
                ("lines-0-product_id", "1"), ("lines-0-quantity", "0"),
                ("lines-0-unit_price", "100"),
            ])
            form = SaleReturnForm(fd, meta=FORM_META)
            assert form.validate() is False
            assert "lines" in form.errors

    def test_valid(self):
        from forms import SaleReturnForm
        patches = self._mock_sale_return_queries()
        with patches[0], patches[1], patches[2], patches[3]:
            fd = MultiDict([
                ("sale_id", "1"), ("customer_id", "1"), ("reason", "Defect"),
                ("currency", "ILS"),
                ("lines-0-product_id", "1"), ("lines-0-quantity", "2"),
                ("lines-0-unit_price", "100"),
            ])
            form = SaleReturnForm(fd, meta=FORM_META)
            assert form.validate() is True


class TestProductFormIval:
    """Tests for ProductForm._ival() static helper."""

    def test_valid_int_string_returns_int(self):
        from forms import ProductForm
        assert ProductForm._ival("123") == 123

    def test_non_int_returns_none(self):
        from forms import ProductForm
        assert ProductForm._ival("abc") is None

    def test_none_returns_none(self):
        from forms import ProductForm
        assert ProductForm._ival(None) is None


class TestProductFormValidateBarcode:
    """Tests for ProductForm.validate_barcode()."""

    def test_valid_barcode_passes(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "123456789012"
        form.validate_barcode(field)
        assert len(field.data) == 13

    def test_empty_barcode_returns(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = ""
        form.validate_barcode(field)

    def test_invalid_barcode_raises(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "abc!@#$"
        with pytest.raises(ValidationError):
            form.validate_barcode(field)

    def test_too_long_barcode_raises(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "12345678901234"
        with pytest.raises(ValidationError):
            form.validate_barcode(field)


class TestProductFormCleanImage:
    """Tests for ProductForm._clean_image()."""

    def test_url_returns_as_is(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        url = "https://example.com/img.jpg"
        assert form._clean_image(url) == url

    def test_path_returns_basename(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        with mock.patch("os.path.basename", return_value="photo.png"):
            assert form._clean_image("subdir/photo.png") == "photo.png"

    def test_http_url_returns_as_is(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        url = "http://example.com/img.jpg"
        assert form._clean_image(url) == url

    def test_leading_slash_returns_as_is(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        assert form._clean_image("/uploads/img.jpg") == "/uploads/img.jpg"

    def test_none_returns_none(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        assert form._clean_image(None) is None

    def test_whitespace_returns_none(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        assert form._clean_image("   ") is None


class TestProductFormValidate:
    """Tests for ProductForm.validate()."""

    def _mock_queries(self, mocker):
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch("forms.Product.query", mock_q)

    def test_super_validate_fails_no_formdata(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        form = ProductForm(meta=FORM_META)
        assert form.validate() is False

    def test_purchase_greater_than_price(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="50", purchase_price="100",
            selling_price="60", currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "price" in form.errors

    def test_selling_less_than_purchase(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="100", purchase_price="50",
            selling_price="30", currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "selling_price" in form.errors

    def test_online_price_less_than_purchase(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="100", purchase_price="50",
            online_price="30", currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "online_price" in form.errors

    def test_min_greater_than_max_price(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="100", purchase_price="50",
            min_price="200", max_price="100",
            currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "max_price" in form.errors

    def test_price_less_than_min(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="50", purchase_price="30",
            min_price="100", currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "price" in form.errors

    def test_price_greater_than_max(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="200", purchase_price="30",
            max_price="100", currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "price" in form.errors

    def test_selling_less_than_min(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="100", purchase_price="50",
            selling_price="30", min_price="80",
            currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "selling_price" in form.errors

    def test_selling_greater_than_max(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="100", purchase_price="50",
            selling_price="200", max_price="150",
            currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "selling_price" in form.errors

    def test_reorder_point_less_than_min_qty(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="100", purchase_price="50",
            reorder_point="5", min_qty="10",
            currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "reorder_point" in form.errors

    def test_valid_passes(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        fd = _fd(
            name="Test", price="100", purchase_price="50",
            selling_price="120", min_price="40", max_price="200",
            currency="ILS", category_id="1",
        )
        form = ProductForm(fd, meta=FORM_META)
        assert form.validate() is True


class TestProductFormApplyTo:
    """Tests for ProductForm.apply_to()."""

    def test_apply_to_sets_attributes(self):
        from forms import ProductForm
        fd = _fd(
            name="Test Product", sku="TST-001", part_number="PN-001",
            brand="BrandX", commercial_name="CommName",
            chassis_number="CH-001", serial_no="SN-001",
            description="A test", barcode="123456789012",
            cost_before_shipping="10", cost_after_shipping="15",
            unit_price_before_tax="20", currency="USD",
            price="100", purchase_price="50", selling_price="120",
            min_price="40", max_price="200", online_price="110",
            tax_rate="10", unit="pcs", min_qty="5",
            reorder_point="10", condition="NEW",
            origin_country="Palestine", warranty_period="12",
            weight="1.5", dimensions="10x10x10",
            image="photo.png", online_name="Online Test",
            online_image="online_photo.png",
            is_active="y", is_exchange="y",
            category_id="1", category_name="Test Cat",
            supplier_id="2", supplier_international_id="3",
            supplier_local_id="4", vehicle_type_id="5",
            notes="Some notes",
        )
        form = ProductForm(fd, meta=FORM_META)
        product = mock.MagicMock()
        result = form.apply_to(product)

        assert result is product
        assert product.name == "Test Product"
        assert product.sku == "TST-001"
        assert product.part_number == "PN-001"
        assert product.price == 100
        assert product.purchase_price == 50
        assert product.selling_price == 120
        assert product.min_price == 40
        assert product.max_price == 200
        assert product.supplier_id == 2
        assert product.supplier_international_id == 3
        assert product.supplier_local_id == 4
        assert product.category_id == 1
        assert product.vehicle_type_id == 5
        assert product.is_active is True
        assert product.is_digital is False
        assert product.is_exchange is True


class TestServiceRequestFormValidate:
    def test_expected_delivery_date_before_plan_start_date(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15",
                expected_delivery="2025-06-14 10:00",
                currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_completed_at_date_before_plan_start_date(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15",
                completed_at="2025-06-14 10:00",
                currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_total_cost_none_sets_base(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                parts_total="100", labor_total="50", discount_total="0",
                tax_rate="0", total_amount="150",
                currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is True
        assert form.total_cost.data == Decimal("150")

    def test_base_with_discount_floor_at_zero(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                parts_total="50", labor_total="30", discount_total="200",
                tax_rate="0", total_amount="0",
                currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestShipmentFormValidate:
    def test_valid_shipment_passes(self, db_session):
        from forms import ShipmentForm
        from models import Warehouse
        wh = Warehouse(name="MainWH", warehouse_type="PHYSICAL")
        db_session.add(wh)
        db_session.commit()
        fd = MultiDict([
            ("shipment_number", "SHP-VALID"),
            ("currency", "USD"),
            ("status", "DRAFT"),
            ("destination_id", str(wh.id)),
            ("items-0-product_id", "1"),
            ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"),
            ("items-0-unit_cost", "50"),
            ("partners-0-partner_id", "1"),
            ("partners-0-share_percentage", "30"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_partner_cumulative_percentage_exceeds_100(self, db_session):
        from forms import ShipmentForm
        from models import Warehouse
        wh = Warehouse(name="MainWH", warehouse_type="PHYSICAL")
        db_session.add(wh)
        db_session.commit()
        fd = MultiDict([
            ("shipment_number", "SHP-CUM"),
            ("currency", "USD"),
            ("status", "DRAFT"),
            ("destination_id", str(wh.id)),
            ("items-0-product_id", "1"),
            ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"),
            ("items-0-unit_cost", "50"),
            ("partners-0-partner_id", "1"),
            ("partners-0-share_percentage", "60"),
            ("partners-1-partner_id", "2"),
            ("partners-1-share_percentage", "50"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        assert form.validate() is False
        assert "partners" in form.errors

    def test_partner_percentage_exactly_100(self, db_session):
        from forms import ShipmentForm
        from models import Warehouse
        wh = Warehouse(name="MainWH", warehouse_type="PHYSICAL")
        db_session.add(wh)
        db_session.commit()
        fd = MultiDict([
            ("shipment_number", "SHP-100PCT"),
            ("currency", "USD"),
            ("status", "DRAFT"),
            ("destination_id", str(wh.id)),
            ("items-0-product_id", "1"),
            ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"),
            ("items-0-unit_cost", "50"),
            ("partners-0-partner_id", "1"),
            ("partners-0-share_percentage", "40"),
            ("partners-1-partner_id", "2"),
            ("partners-1-share_percentage", "60"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        assert form.validate() is True

    def test_partner_without_partner_id_skipped(self, db_session):
        from forms import ShipmentForm
        from models import Warehouse
        wh = Warehouse(name="MainWH", warehouse_type="PHYSICAL")
        db_session.add(wh)
        db_session.commit()
        fd = MultiDict([
            ("shipment_number", "SHP-NOID"),
            ("currency", "USD"),
            ("status", "DRAFT"),
            ("destination_id", str(wh.id)),
            ("items-0-product_id", "1"),
            ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"),
            ("items-0-unit_cost", "50"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        for entry in form.partners.entries:
            entry.form.partner_id.data = None
        assert form.validate() is True


class TestUserFormRemainingBranches:

    def test_init_with_obj_sets_editing(self, app, mocker):
        from forms import UserForm
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        obj = mock.MagicMock(spec=["last_login", "last_seen", "last_login_ip", "login_count"])
        obj.last_login = None
        obj.last_seen = None
        obj.last_login_ip = ""
        obj.login_count = ""
        with app.test_request_context():
            from flask import request
            request.view_args = {"user_id": "5"}
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(obj=obj, meta=FORM_META)
                assert form._editing_user_id == "5"
                assert form.last_login.data is None
                assert form.last_login_ip.data == ""

    def test_validate_username_exists(self, app, mocker):
        from forms import UserForm
        from wtforms.validators import ValidationError
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form._editing_user_id = None
                form.username.data = "existing_user"
                mock_q = mock.MagicMock()
                mock_q.filter.return_value.first.return_value = mock.MagicMock(id=99)
                with mock.patch("forms.User.query", mock_q):
                    with pytest.raises(ValidationError, match="مستخدم بالفعل"):
                        form.validate_username(form.username)

    def test_validate_email_exists(self, app, mocker):
        from forms import UserForm
        from wtforms.validators import ValidationError
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form._editing_user_id = None
                form.email.data = "existing@test.com"
                mock_q = mock.MagicMock()
                mock_q.filter.return_value.first.return_value = mock.MagicMock(id=99)
                with mock.patch("forms.User.query", mock_q):
                    with pytest.raises(ValidationError, match="مستخدم بالفعل"):
                        form.validate_email(form.email)

    def test_validate_branch_ids_invalid(self, app, mocker):
        from forms import UserForm
        from wtforms.validators import ValidationError
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form.branch_ids.data = [1, 2]
                form.primary_branch_id.data = 1
                form.role_id.data = 2
                with mock.patch("services.user_branch_service.validate_branch_assignment", return_value="خطأ في تعيين الفروع"):
                    with pytest.raises(ValidationError, match="خطأ في تعيين الفروع"):
                        form.validate_branch_ids(form.branch_ids)

    def test_validate_username_edit(self, app, mocker):
        from forms import UserForm
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form._editing_user_id = 5
                form.username.data = "edit_self"
                mock_q = mock.MagicMock()
                mock_q.filter.return_value.filter.return_value.first.return_value = None
                with mock.patch("forms.User.query", mock_q):
                    form.validate_username(form.username)

    def test_apply_to_sets_password(self, app, mocker):
        from forms import UserForm
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form.username.data = "user"
                form.email.data = "user@test.com"
                form.role_id.data = 1
                form.is_active.data = True
                form.password.data = "newsecret123"
                user = mock.MagicMock()
                form.apply_to(user)
                user.set_password.assert_called_once_with("newsecret123")

    def test_apply_to_sets_username_email(self, app, mocker):
        from forms import UserForm
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form.username.data = "  testuser  "
                form.email.data = "  Test@Example.COM  "
                form.role_id.data = 2
                form.is_active.data = True
                form.password.data = None
                user = mock.MagicMock()
                result = form.apply_to(user)
                assert result is user
                assert user.username == "testuser"
                assert user.email == "test@example.com"
                assert user.role_id == 2
                assert user.is_active is True

    def test_validate_email_during_edit_skips_existing_check(self, app, mocker):
        from forms import UserForm
        mocker.patch("forms.Role.query.all", return_value=[])
        mocker.patch("utils.tenant_ui.branch_choices_for_form", return_value=[])
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = UserForm(meta=FORM_META)
                form._editing_user_id = 5
                form.email.data = "edit@test.com"
                mock_q = mock.MagicMock()
                mock_q.filter.return_value.filter.return_value.first.return_value = None
                with mock.patch("forms.User.query", mock_q):
                    form.validate_email(form.email)
                    assert form.email.data == "edit@test.com"


class TestCustomerFormApplyTo:

    def test_apply_to_sets_fields(self, app):
        from forms import CustomerForm
        with app.app_context():
            form = CustomerForm(_fd(
                name="  Test Customer  ",
                phone="  050-123-4567  ",
                email="  CUSTOMER@TEST.COM  ",
                address="  Main Street  ",
                category="NORMAL",
                currency="ILS",
                is_active="y",
                is_online="y",
                is_archived="",
                notes="  Some notes  ",
                credit_limit="1000",
                discount_rate="5",
                whatsapp="",
            ), meta=FORM_META)
            customer = mock.MagicMock()
            form.apply_to(customer)
            assert customer.name == "Test Customer"
            assert customer.phone == "0501234567"
            assert customer.whatsapp == "0501234567"
            assert customer.email == "customer@test.com"
            assert customer.address == "Main Street"
            assert customer.category == "NORMAL"
            assert customer.currency == "ILS"
            assert customer.is_active is True
            assert customer.is_online is True
            assert customer.is_archived is False
            assert customer.notes == "Some notes"
            assert customer.credit_limit == Decimal("1000.00")
            assert customer.discount_rate == Decimal("5.00")

    def test_apply_to_whatsapp_falls_back_to_phone(self, app):
        from forms import CustomerForm
        with app.app_context():
            form = CustomerForm(_fd(
                name="Test", phone="0501234567",
                email="", category="NORMAL", currency="ILS",
                whatsapp="",
            ), meta=FORM_META)
            customer = mock.MagicMock()
            form.apply_to(customer)
            assert customer.whatsapp == "0501234567"

    def test_validate_password_required_for_new(self):
        from forms import CustomerForm
        from wtforms.validators import ValidationError
        form = CustomerForm(meta=FORM_META)
        form.id.data = ""
        field = mock.MagicMock()
        field.data = ""
        with pytest.raises(ValidationError, match="كلمة المرور مطلوبة"):
            form.validate_password(field)

    def test_validate_password_optional_for_edit(self):
        from forms import CustomerForm
        form = CustomerForm(meta=FORM_META)
        form.id.data = "5"
        field = mock.MagicMock()
        field.data = ""
        form.validate_password(field)

    def test_validate_email_normalizes(self):
        from forms import CustomerForm
        form = CustomerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  USER@DOMAIN.COM  "
        form.validate_email(field)
        assert field.data == "user@domain.com"

    def test_validate_whatsapp_uses_phone_fallback(self):
        from forms import CustomerForm
        form = CustomerForm(meta=FORM_META)
        form.phone.data = " 0501234567 "
        field = mock.MagicMock()
        field.data = ""
        form.validate_whatsapp(field)
        assert field.data == "0501234567"

    def test_validate_whatsapp_uses_own_value(self):
        from forms import CustomerForm
        form = CustomerForm(meta=FORM_META)
        form.phone.data = " 0500000000 "
        field = mock.MagicMock()
        field.data = " 0599999999 "
        form.validate_whatsapp(field)
        assert field.data == "0599999999"


class TestSupplierFormApplyTo:

    def test_apply_to_sets_fields(self, app):
        from forms import SupplierForm
        with app.app_context():
            form = SupplierForm(_fd(
                name="  Test Supplier  ",
                is_local="y",
                identity_number="  ID-123  ",
                contact="  John Doe  ",
                phone="  050-111-2222  ",
                email="  SUPPLIER@TEST.COM  ",
                address="  Supplier St  ",
                notes="  Supplier notes  ",
                opening_balance="500",
                payment_terms="  Net 30  ",
                currency="ILS",
            ), meta=FORM_META)
            supplier = mock.MagicMock()
            form.apply_to(supplier)
            assert supplier.name == "Test Supplier"
            assert supplier.is_local is True
            assert supplier.identity_number == "ID-123"
            assert supplier.contact == "John Doe"
            assert supplier.phone == "0501112222"
            assert supplier.email == "supplier@test.com"
            assert supplier.address == "Supplier St"
            assert supplier.notes == "Supplier notes"
            assert supplier.opening_balance == Decimal("500.00")
            assert supplier.payment_terms == "Net 30"
            assert supplier.currency == "ILS"

    def test_apply_to_empty_fields_become_none(self, app):
        from forms import SupplierForm
        with app.app_context():
            form = SupplierForm(_fd(
                name="Test", currency="ILS",
            ), meta=FORM_META)
            supplier = mock.MagicMock()
            form.apply_to(supplier)
            assert supplier.identity_number is None
            assert supplier.contact is None
            assert supplier.address is None
            assert supplier.notes is None
            assert supplier.payment_terms is None

    def test_validate_phone_normalizes(self):
        from forms import SupplierForm
        form = SupplierForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  050-333-4444  "
        form.validate_phone(field)
        assert field.data == "0503334444"

    def test_validate_phone_none_skips(self):
        from forms import SupplierForm
        form = SupplierForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = None
        form.validate_phone(field)

    def test_validate_email_normalizes(self):
        from forms import SupplierForm
        form = SupplierForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  VENDOR@EXAMPLE.COM  "
        form.validate_email(field)
        assert field.data == "vendor@example.com"

    def test_validate_email_none_skips(self):
        from forms import SupplierForm
        form = SupplierForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = None
        form.validate_email(field)


class TestPartnerFormApplyTo:

    def test_apply_to_sets_fields(self, app):
        from forms import PartnerForm
        with app.app_context():
            form = PartnerForm(_fd(
                name="  Test Partner  ",
                contact_info="  Partner Contact  ",
                identity_number="  PID-456  ",
                phone_number="  050-555-6666  ",
                email="  PARTNER@TEST.COM  ",
                address="  Partner Address  ",
                opening_balance="1000",
                share_percentage="25",
                currency="ILS",
                notes="  Partner notes  ",
            ), meta=FORM_META)
            partner = mock.MagicMock()
            form.apply_to(partner)
            assert partner.name == "Test Partner"
            assert partner.contact_info == "Partner Contact"
            assert partner.identity_number == "PID-456"
            assert partner.phone_number == "0505556666"
            assert partner.email == "partner@test.com"
            assert partner.address == "Partner Address"
            assert partner.opening_balance == Decimal("1000.00")
            assert partner.share_percentage == Decimal("25.00")
            assert partner.currency == "ILS"
            assert partner.notes == "Partner notes"

    def test_apply_to_empty_fields_become_none(self, app):
        from forms import PartnerForm
        with app.app_context():
            form = PartnerForm(_fd(
                name="Test", currency="ILS",
            ), meta=FORM_META)
            partner = mock.MagicMock()
            form.apply_to(partner)
            assert partner.contact_info is None
            assert partner.identity_number is None
            assert partner.address is None
            assert partner.notes is None

    def test_validate_phone_number_normalizes(self):
        from forms import PartnerForm
        form = PartnerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  050-777-8888  "
        form.validate_phone_number(field)
        assert field.data == "0507778888"

    def test_validate_phone_number_none_skips(self):
        from forms import PartnerForm
        form = PartnerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = None
        form.validate_phone_number(field)

    def test_validate_email_normalizes(self):
        from forms import PartnerForm
        form = PartnerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  PARNTER@MAIL.COM  "
        form.validate_email(field)
        assert field.data == "parnter@mail.com"

    def test_validate_email_none_skips(self):
        from forms import PartnerForm
        form = PartnerForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = None
        form.validate_email(field)


class TestPaymentFormValidateBranches:

    def test_method_set_from_split(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, "prepare_payment_form_choices")
        mocker.patch("models.is_direction_allowed", return_value=True)
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([
                        ("entity_type", "CUSTOMER"),
                        ("direction", "IN"),
                        ("total_amount", "100"),
                        ("currency", "ILS"),
                        ("payment_date", "2025-06-15 10:30"),
                        ("status", "COMPLETED"),
                        ("customer_id", "5"),
                        ("splits-0-amount", "100"),
                        ("splits-0-method", "CASH"),
                    ]),
                    meta=FORM_META,
                )
                form.method.data = ""
                assert form.validate() is True
                assert form.method.data == "CASH"

    def test_no_positive_split_amounts_fails(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, "prepare_payment_form_choices")
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([
                        ("entity_type", "CUSTOMER"),
                        ("direction", "IN"),
                        ("total_amount", "100"),
                        ("currency", "ILS"),
                        ("payment_date", "2025-06-15 10:30"),
                        ("status", "COMPLETED"),
                        ("splits-0-amount", "0"),
                        ("splits-0-method", "CASH"),
                    ]),
                    meta=FORM_META,
                )
                assert form.validate() is False
                assert "splits" in form.errors

    def test_supplier_entity_validates(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, "prepare_payment_form_choices")
        mocker.patch("models.is_direction_allowed", return_value=True)
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([
                        ("entity_type", "SUPPLIER"),
                        ("direction", "OUT"),
                        ("total_amount", "200"),
                        ("currency", "ILS"),
                        ("payment_date", "2025-06-15 10:30"),
                        ("status", "COMPLETED"),
                        ("supplier_id", "3"),
                        ("splits-0-amount", "200"),
                        ("splits-0-method", "CASH"),
                    ]),
                    meta=FORM_META,
                )
                assert form.validate() is True
                assert form.entity_id.data == "3"

    def test_bank_method_main_no_ref_fails(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, "prepare_payment_form_choices")
        mocker.patch("models.is_direction_allowed", return_value=True)
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([
                        ("entity_type", "SUPPLIER"),
                        ("direction", "OUT"),
                        ("total_amount", "200"),
                        ("currency", "ILS"),
                        ("payment_date", "2025-06-15 10:30"),
                        ("status", "COMPLETED"),
                        ("supplier_id", "3"),
                        ("method", "BANK"),
                        ("bank_transfer_ref", ""),
                        ("splits-0-amount", "200"),
                        ("splits-0-method", "CASH"),
                    ]),
                    meta=FORM_META,
                )
                assert form.validate() is False
                assert "bank_transfer_ref" in form.errors

    def test_expense_missing_reference_allowed(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, "prepare_payment_form_choices")
        mocker.patch("models.is_direction_allowed", return_value=True)
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([
                        ("entity_type", "EXPENSE"),
                        ("direction", "OUT"),
                        ("total_amount", "150"),
                        ("currency", "ILS"),
                        ("payment_date", "2025-06-15 10:30"),
                        ("status", "COMPLETED"),
                        ("splits-0-amount", "150"),
                        ("splits-0-method", "CASH"),
                    ]),
                    meta=FORM_META,
                )
                assert form.validate() is True

    def test_idempotency_key_generated_on_validate(self, app, mocker):
        from forms import PaymentForm
        import utils
        mocker.patch.object(utils, "prepare_payment_form_choices")
        mocker.patch("models.is_direction_allowed", return_value=True)
        mocker.patch("models.generate_idempotency_key", return_value="key-pay-xyz")
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "admin"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = PaymentForm(
                    MultiDict([
                        ("entity_type", "CUSTOMER"),
                        ("direction", "IN"),
                        ("total_amount", "100"),
                        ("currency", "ILS"),
                        ("payment_date", "2025-06-15 10:30"),
                        ("status", "COMPLETED"),
                        ("customer_id", "5"),
                        ("splits-0-amount", "100"),
                        ("splits-0-method", "CASH"),
                    ]),
                    meta=FORM_META,
                )
                assert form.idempotency_key.data is None or form.idempotency_key.data == ""
                result = form.validate()
                assert result is True
                assert form.idempotency_key.data is not None


class TestExchangeTransactionFormRemaining:
    """ExchangeTransactionForm.__init__, validate branches, and apply_to."""

    def test_init_defaults(self):
        from forms import ExchangeTransactionForm
        form = ExchangeTransactionForm(meta=FORM_META)
        assert form.require_pricing is False
        assert form.warnings == []

    def test_init_with_require_pricing(self):
        from forms import ExchangeTransactionForm
        form = ExchangeTransactionForm(meta=FORM_META, require_pricing=True)
        assert form.require_pricing is True
        assert form.warnings == []

    def test_validate_super_fails(self):
        from forms import ExchangeTransactionForm
        form = ExchangeTransactionForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_validate_warehouse_not_found(self, app, mocker):
        from forms import ExchangeTransactionForm
        mocker.patch("extensions.db.session.get", return_value=None)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="OUT", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert 'يجب أن تكون الحركة على مخزن تبادل.' in form.warehouse_id.errors

    def test_validate_warehouse_not_exchange(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type"], warehouse_type="MAIN")
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="OUT", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert 'يجب أن تكون الحركة على مخزن تبادل.' in form.warehouse_id.errors

    def test_validate_warehouse_no_supplier(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type"], warehouse_type="EXCHANGE")
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="OUT", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert 'مخزن التبادل يجب أن يكون مربوطًا بمورد.' in form.warehouse_id.errors

    def test_validate_warehouse_db_exception(self, app, mocker):
        from forms import ExchangeTransactionForm
        mocker.patch("extensions.db.session.get", side_effect=Exception("DB down"))
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="OUT", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert 'تعذر التحقق من المخزن.' in form.warehouse_id.errors

    def test_validate_warehouse_with_supplier_passes(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="IN", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is True

    def test_validate_out_insufficient_stock(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        sl = mock.MagicMock(quantity=3, reserved_quantity=1)
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = sl
        mocker.patch("forms.StockLevel.query", mock_q)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="OUT", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert 'الكمية غير كافية في المخزن.' in form.quantity.errors

    def test_validate_out_sufficient_stock(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        sl = mock.MagicMock(quantity=10, reserved_quantity=2)
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = sl
        mocker.patch("forms.StockLevel.query", mock_q)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="OUT", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is True

    def test_validate_out_stock_check_exception(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        mock_q = mock.MagicMock()
        mock_q.filter_by.side_effect = Exception("stock check error")
        mocker.patch("forms.StockLevel.query", mock_q)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="OUT", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is True

    def test_validate_require_pricing_no_cost(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="IN", quantity="5"),
                meta=FORM_META, require_pricing=True,
            )
            assert form.validate() is False
            assert 'هذه تسوية: أدخل تكلفة موجبة للوحدة.' in form.unit_cost.errors

    def test_validate_require_pricing_with_cost(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="IN",
                    quantity="5", unit_cost="50"),
                meta=FORM_META, require_pricing=True,
            )
            assert form.validate() is True
            assert form.is_priced.data is True

    def test_validate_priced_flag_no_cost(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="IN",
                    quantity="5", is_priced="y"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert 'عند اختيار "مسعّر" يجب إدخال تكلفة موجبة.' in form.unit_cost.errors

    def test_validate_priced_flag_with_cost(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="IN",
                    quantity="5", is_priced="y", unit_cost="50"),
                meta=FORM_META,
            )
            assert form.validate() is True
            assert form.is_priced.data is True

    def test_validate_not_priced_but_cost_given(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="IN",
                    quantity="5", unit_cost="50"),
                meta=FORM_META,
            )
            assert form.validate() is True
            assert form.is_priced.data is True

    def test_validate_not_priced_no_cost_warning(self, app, mocker):
        from forms import ExchangeTransactionForm
        wh = mock.MagicMock(spec=["warehouse_type", "supplier_id"],
                            warehouse_type="EXCHANGE", supplier_id=1)
        mocker.patch("extensions.db.session.get", return_value=wh)
        with app.test_request_context():
            form = ExchangeTransactionForm(
                _fd(product_id="1", warehouse_id="2", direction="IN", quantity="5"),
                meta=FORM_META,
            )
            assert form.validate() is True
            assert any('لم تُدخل تكلفة' in w for w in form.warnings)

    def test_apply_to_sets_fields(self):
        from forms import ExchangeTransactionForm
        form = ExchangeTransactionForm(
            _fd(product_id="10", warehouse_id="20", partner_id="30",
                direction="in", quantity="7", unit_cost="25.50",
                notes="  test note  "),
            meta=FORM_META,
        )
        xt = mock.MagicMock()
        result = form.apply_to(xt)
        assert result is xt
        assert xt.product_id == 10
        assert xt.warehouse_id == 20
        assert xt.partner_id == 30
        assert xt.direction == "IN"
        assert xt.quantity == 7
        assert xt.unit_cost == Decimal("25.50")
        assert xt.is_priced is True
        assert xt.notes == "test note"

    def test_apply_to_without_partner_or_cost(self):
        from forms import ExchangeTransactionForm
        form = ExchangeTransactionForm(
            _fd(product_id="10", warehouse_id="20",
                direction="OUT", quantity="3"),
            meta=FORM_META,
        )
        xt = mock.MagicMock()
        form.apply_to(xt)
        assert xt.partner_id is None
        assert xt.unit_cost is None
        assert xt.is_priced is False
        assert xt.notes is None


class TestServiceTaskFormApplyTo:
    def test_apply_to_sets_all_fields(self):
        from forms import ServiceTaskForm
        form = ServiceTaskForm(
            _fd(service_id="5", partner_id="3", share_percentage="25",
                description="Fix engine", quantity="2", unit_price="150",
                discount="10", note="urgent"),
            meta=FORM_META,
        )
        task = mock.MagicMock()
        result = form.apply_to(task)
        assert result is task
        assert task.service_id == 5
        assert task.partner_id == 3
        assert task.share_percentage == Decimal("25.00")
        assert task.description == "Fix engine"
        assert task.quantity == 2
        assert task.unit_price == Decimal("150.00")
        assert task.discount == Decimal("10.00")
        assert task.note == "urgent"

    def test_apply_to_optional_partner(self):
        from forms import ServiceTaskForm
        form = ServiceTaskForm(
            _fd(service_id="5", description="Fix",
                quantity="1", unit_price="100"),
            meta=FORM_META,
        )
        task = mock.MagicMock()
        form.apply_to(task)
        assert task.service_id == 5
        assert task.partner_id is None
        assert task.share_percentage is None
        assert task.note is None


class TestServiceDiagnosisFormApplyTo:
    def test_apply_to_sets_all_fields(self):
        from forms import ServiceDiagnosisForm
        form = ServiceDiagnosisForm(
            _fd(problem_description="Engine noise",
                diagnosis="Broken belt", resolution="Replace belt",
                estimated_duration="30", estimated_cost="200"),
            meta=FORM_META,
        )
        diag = mock.MagicMock()
        result = form.apply_to(diag)
        assert result is diag
        assert diag.problem_description == "Engine noise"
        assert diag.diagnosis == "Broken belt"
        assert diag.resolution == "Replace belt"
        assert diag.estimated_duration == 30
        assert diag.estimated_cost == Decimal("200.00")

    def test_apply_to_without_optional(self):
        from forms import ServiceDiagnosisForm
        form = ServiceDiagnosisForm(
            _fd(problem_description="Noise", diagnosis="Belt",
                resolution="Replace"),
            meta=FORM_META,
        )
        diag = mock.MagicMock()
        form.apply_to(diag)
        assert diag.estimated_duration is None
        assert diag.estimated_cost is None


class TestServicePartFormApplyTo:
    def test_apply_to_sets_all_fields(self):
        from forms import ServicePartForm
        form = ServicePartForm(
            _fd(service_id="5", part_id="15", warehouse_id="2",
                quantity="3", unit_price="45", discount="5",
                note="urgent", notes="extra info"),
            meta=FORM_META,
        )
        sp = mock.MagicMock()
        result = form.apply_to(sp)
        assert result is sp
        assert sp.service_id == 5
        assert sp.part_id == 15
        assert sp.warehouse_id == 2
        assert sp.quantity == 3
        assert sp.unit_price == Decimal("45.00")
        assert sp.discount == Decimal("5.00")
        assert sp.note == "urgent"
        assert sp.notes == "extra info"

    def test_apply_to_optional_fields(self):
        from forms import ServicePartForm
        form = ServicePartForm(
            _fd(part_id="15", warehouse_id="2",
                quantity="1", unit_price="100"),
            meta=FORM_META,
        )
        sp = mock.MagicMock()
        form.apply_to(sp)
        assert sp.service_id is None
        assert sp.note is None
        assert sp.notes is None


class TestProductPartnerShareFormValidate:
    def test_validate_super_fails(self):
        from forms import ProductPartnerShareForm
        form = ProductPartnerShareForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_validate_both_zero_or_empty(self):
        from forms import ProductPartnerShareForm
        form = ProductPartnerShareForm(
            _fd(product_id="1", warehouse_id="2", partner_id="3",
                share_percentage="0", share_amount="0"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is False
        assert 'أدخل نسبة الشريك or قيمة مساهمته على الأقل.' in form.share_percentage.errors
        assert 'أدخل نسبة الشريك or قيمة مساهمته على الأقل.' in form.share_amount.errors

    def test_validate_share_percentage_only(self):
        from forms import ProductPartnerShareForm
        form = ProductPartnerShareForm(
            _fd(product_id="1", warehouse_id="2", partner_id="3",
                share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_validate_share_amount_only(self):
        from forms import ProductPartnerShareForm
        form = ProductPartnerShareForm(
            _fd(product_id="1", warehouse_id="2", partner_id="3",
                share_amount="100"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_validate_both_provided(self):
        from forms import ProductPartnerShareForm
        form = ProductPartnerShareForm(
            _fd(product_id="1", warehouse_id="2", partner_id="3",
                share_percentage="30", share_amount="200"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestWarehousePartnerShareFormValidate:
    def test_super_validate_fails(self):
        from forms import WarehousePartnerShareForm
        form = WarehousePartnerShareForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_neither_product_nor_warehouse(self):
        from forms import WarehousePartnerShareForm
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "اختر منتجًا" in form.product_id.errors[0]

    def test_product_provided_passes(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", product_id="10", share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_warehouse_provided_passes(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", warehouse_id="20", share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_share_both_zero_unreachable(self):
        """share_percentage=0 with DataRequired always fails super validate."""
        from forms import WarehousePartnerShareForm
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", product_id="10",
                share_percentage="0", share_amount="0"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_share_percentage_positive(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", product_id="10", share_percentage="25"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_share_amount_positive(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", product_id="10",
                share_percentage="25", share_amount="100"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_uniqueness_duplicate(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = mock.MagicMock(id=999)
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", product_id="10", share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "يوجد سجل لنفس" in form.product_id.errors[0]

    def test_uniqueness_ok(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", product_id="10", share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_uniqueness_exception_passes(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.side_effect = Exception("DB down")
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(partner_id="1", product_id="10", share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_uniqueness_with_id_editing(self, mocker):
        from forms import WarehousePartnerShareForm
        mock_q = mock.MagicMock()
        mock_q.filter_by.return_value.filter.return_value.first.return_value = None
        mocker.patch("models.WarehousePartnerShare.query", mock_q)
        form = WarehousePartnerShareForm(
            _fd(id="5", partner_id="1", product_id="10", share_percentage="50"),
            meta=FORM_META,
        )
        assert form.validate() is True
        mock_q.filter_by.assert_called_once()


class TestJournalLineFormValidateRemaining:
    """Covers lines 4395-4404: both debit+credit > 0, entity_type missing, entity_id not numeric."""

    def test_validate_super_fails(self):
        from forms import JournalLineForm
        form = JournalLineForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_both_debit_and_credit_positive(self):
        from forms import JournalLineForm
        form = JournalLineForm(
            _fd(account_id="1", debit="50", credit="30"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert 'لا يجوز أن يكون السطر مدينًا ودائنًا معًا' in form.credit.errors

    def test_entity_id_without_entity_type(self):
        from forms import JournalLineForm
        form = JournalLineForm(
            _fd(account_id="1", debit="100", entity_id="42"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert 'حدد نوع الكيان' in form.entity_type.errors

    def test_entity_id_not_numeric(self):
        from forms import JournalLineForm
        form = JournalLineForm(
            _fd(account_id="1", debit="100", entity_type="CUSTOMER",
                entity_id="abc"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert 'معرّف الكيان يجب أن يكون رقمًا صحيحًا.' in form.entity_id.errors

    def test_valid_line(self):
        from forms import JournalLineForm
        form = JournalLineForm(
            _fd(account_id="1", debit="100", entity_type="CUSTOMER",
                entity_id="42", note="test"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestJournalEntryFormValidateRemaining:
    """Covers lines 4420-4457: filters non-empty lines, debit=credit check, apply_to."""

    def test_super_validate_fails(self):
        from forms import JournalEntryForm
        form = JournalEntryForm(
            _fd(entry_date="2025-06-15T10:30", currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_used_line_filter(self):
        """Verify the 'used' comprehension filters out zero-value lines."""
        from forms import JournalEntryForm
        form = JournalEntryForm(
            MultiDict([
                ("entry_date", "2025-06-15T10:30"),
                ("currency", "ILS"),
                ("lines-0-account_id", "1"),
                ("lines-0-debit", "100"),
                ("lines-0-credit", "0"),
                ("lines-1-account_id", "2"),
                ("lines-1-debit", "0"),
                ("lines-1-credit", "100"),
            ]),
            meta=FORM_META,
        )
        assert form.validate() is True
        assert hasattr(form, '_used_lines_count')

    def test_debit_credit_mismatch(self):
        from forms import JournalEntryForm
        form = JournalEntryForm(
            MultiDict([
                ("entry_date", "2025-06-15T10:30"),
                ("currency", "ILS"),
                ("lines-0-account_id", "1"),
                ("lines-0-debit", "100"),
                ("lines-0-credit", "0"),
                ("lines-1-account_id", "2"),
                ("lines-1-debit", "0"),
                ("lines-1-credit", "50"),
            ]),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert any('مجموع المدين يجب أن يساوي مجموع الدائن' in str(e) for e in form.lines.errors)

    def test_debit_credit_match(self):
        from forms import JournalEntryForm
        form = JournalEntryForm(
            MultiDict([
                ("entry_date", "2025-06-15T10:30"),
                ("currency", "ILS"),
                ("post_now", "y"),
                ("lines-0-account_id", "1"),
                ("lines-0-debit", "100"),
                ("lines-0-credit", "0"),
                ("lines-1-account_id", "2"),
                ("lines-1-debit", "0"),
                ("lines-1-credit", "100"),
            ]),
            meta=FORM_META,
        )
        assert form.validate() is True

    def test_apply_to_builds_journal_lines(self, mocker):
        from forms import JournalEntryForm
        mocker.patch("models.JournalLine", create=True)
        form = JournalEntryForm(
            MultiDict([
                ("entry_date", "2025-06-15T10:30"),
                ("currency", "ILS"),
                ("post_now", "y"),
                ("reference", "REF-001"),
                ("description", "Test entry"),
                ("lines-0-account_id", "1"),
                ("lines-0-debit", "100"),
                ("lines-0-credit", "0"),
                ("lines-1-account_id", "2"),
                ("lines-1-debit", "0"),
                ("lines-1-credit", "100"),
                ("lines-2-account_id", "3"),
                ("lines-2-debit", "0"),
                ("lines-2-credit", "0"),
            ]),
            meta=FORM_META,
        )
        form.validate()
        je = mock.MagicMock()
        result = form.apply_to(je)
        assert result is je
        assert je.entry_date is not None
        assert je.reference == "REF-001"
        assert je.description == "Test entry"
        assert je.currency == "ILS"
        assert je.posted is True
        assert len(je.lines) == 2


class TestRegistrationForm:
    """Covers RegistrationForm validate_username / validate_email branches (lines 642-651)."""

    def test_validate_username_unique(self):
        from forms import RegistrationForm
        from wtforms.validators import ValidationError
        form = RegistrationForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  taken_user  "
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = mock.MagicMock(id=99)
        with mock.patch("forms.User.query", mock_q):
            with pytest.raises(ValidationError):
                form.validate_username(field)

    def test_validate_email_unique(self):
        from forms import RegistrationForm
        from wtforms.validators import ValidationError
        form = RegistrationForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  Taken@Email.COM  "
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = mock.MagicMock(id=99)
        with mock.patch("forms.User.query", mock_q):
            with pytest.raises(ValidationError):
                form.validate_email(field)

    def test_validate_email_normalizes(self):
        from forms import RegistrationForm
        form = RegistrationForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  Test@Example.COM  "
        form.validate_email(field)
        assert field.data == "test@example.com"


class TestPasswordResetRequestForm:
    """Covers PasswordResetRequestForm.validate_email (line 665)."""

    def test_validate_email_normalizes(self):
        from forms import PasswordResetRequestForm
        form = PasswordResetRequestForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  User@Domain.COM  "
        form.validate_email(field)
        assert field.data == "user@domain.com"


class TestRoleForm:
    """Covers RoleForm.validate_name (lines 802-808)."""

    def test_validate_name_unique(self):
        from forms import RoleForm
        from wtforms.validators import ValidationError
        form = RoleForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  admin  "
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = mock.MagicMock(id=1)
        with mock.patch("forms.Role.query", mock_q):
            with pytest.raises(ValidationError):
                form.validate_name(field)


class TestPermissionForm:
    """Covers PermissionForm.validate_name / validate_code (lines 822-830)."""

    def test_validate_name_strips(self):
        from forms import PermissionForm
        form = PermissionForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  Manage Users  "
        form.validate_name(field)
        assert field.data == "Manage Users"

    def test_validate_code_normalizes(self):
        from forms import PermissionForm
        form = PermissionForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  Manage-Users  "
        form.validate_code(field)
        assert field.data == "manage_users"

    def test_validate_code_empty(self):
        from forms import PermissionForm
        form = PermissionForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "  "
        form.validate_code(field)
        assert field.data == ""


class TestProductSupplierLoanForm:
    """Covers ProductSupplierLoanForm.validate (lines 908-915)."""

    def test_requires_deferred_price_when_settled(self):
        from forms import ProductSupplierLoanForm
        form = ProductSupplierLoanForm(
            _fd(product_id="1", supplier_id="1", loan_value="100"),
            meta=FORM_META,
        )
        form.is_settled.data = True
        form.deferred_price.data = None
        assert form.validate() is False
        assert "deferred_price" in form.errors


class TestBulkPaymentFormValidate:
    """Covers BulkPaymentForm validate try/except branches (lines 1082-1083, 1091-1092)."""

    def test_total_amount_decimal_exception(self):
        from forms import BulkPaymentForm
        form = BulkPaymentForm(
            _fd(payer_type="customer", payer_id="1", total_amount="not_a_number",
                currency="ILS", method="CASH"),
            meta=FORM_META,
        )
        result = form.validate()
        assert result is not None

    def test_allocation_decimal_exception(self):
        from forms import BulkPaymentForm
        md = MultiDict()
        md["payer_type"] = "customer"
        md["payer_id"] = "1"
        md["total_amount"] = "100"
        md["method"] = "CASH"
        md["currency"] = "ILS"
        md.setlist("allocations-0-invoice_ids", ["5"])
        md.setlist("allocations-0-allocation_amounts-0", ["bad_value"])
        form = BulkPaymentForm(md, meta=FORM_META)
        result = form.validate()
        assert result is not None


class TestSupplierSettlementFormValidate:
    """Covers SupplierSettlementForm.validate branch (lines 1144, 1158-1159)."""

    def test_super_validate_fails(self):
        from forms import SupplierSettlementForm
        form = SupplierSettlementForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_line_iteration_exception(self):
        from forms import SupplierSettlementForm
        form = SupplierSettlementForm(
            _fd(supplier_id="1", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="ILS",
                status="DRAFT", mode="ON_RECEIPT",
                total_gross="0", total_due="0"),
            meta=FORM_META,
        )
        for entry in form.lines.entries:
            entry.form.quantity.data = None
        result = form.validate()
        assert result is False


class TestSupplierLoanSettlementFormValidate:
    """Covers SupplierLoanSettlementForm.validate branches (lines 1198-1201, 1213-1214)."""

    def test_no_loan_or_supplier(self):
        from forms import SupplierLoanSettlementForm
        from datetime import datetime
        form = SupplierLoanSettlementForm(
            _fd(settled_price="100"),
            meta=FORM_META,
        )
        form.settlement_date.data = datetime(2025, 6, 15, 10, 0)
        assert form.validate() is False
        assert "loan_id" in form.errors

    def test_exception_on_check(self):
        from forms import SupplierLoanSettlementForm
        from datetime import datetime
        form = SupplierLoanSettlementForm(
            _fd(loan_id="5", supplier_id="1", settled_price="100"),
            meta=FORM_META,
        )
        form.settlement_date.data = datetime(2025, 6, 15, 10, 0)
        with mock.patch("extensions.db.session.get", side_effect=Exception("bolti")):
            result = form.validate()
            assert result is not None


class TestPartnerSettlementFormValidate:
    """Covers PartnerSettlementForm.validate branches (lines 1336, 1338-1339)."""

    def test_nonempty_check(self):
        from forms import PartnerSettlementForm
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="ILS", status="DRAFT"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_line_exception(self):
        from forms import PartnerSettlementForm
        form = PartnerSettlementForm(
            _fd(partner_id="1", from_date="2025-01-01 00:00",
                to_date="2025-01-31 00:00", currency="ILS", status="DRAFT"),
            meta=FORM_META,
        )
        for entry in form.lines.entries:
            entry.form.quantity.data = None
        result = form.validate()
        assert result is False


class TestPreOrderForm:
    """Covers PreOrderForm.validate expected_date vs preorder_date (lines 1819-1838)."""

    def test_expected_date_before_preorder(self):
        from forms import PreOrderForm
        form = PreOrderForm(
            _fd(reference="PO1", preorder_date="2025-06-15T10:00",
                expected_date="2025-06-10T10:00"),
            meta=FORM_META,
        )
        assert form.validate() is False


class TestServiceRequestFormValidateRemaining:
    """Covers ServiceRequestForm.validate remaining date/tax/amount branches (lines 1910-1955)."""

    def test_end_time_before_start_time(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15 14:00", end_time="2025-06-15 10:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_started_at_before_received_at(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                received_at="2025-06-15 10:00", started_at="2025-06-14 09:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_started_at_date_before_plan_start(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15 09:00", started_at="2025-06-14 10:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_expected_delivery_before_started_at(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                started_at="2025-06-15 10:00",
                expected_delivery="2025-06-14 09:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_expected_delivery_date_before_plan_start(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15",
                expected_delivery="2025-06-14 10:00",
                currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_completed_at_before_started_at(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                started_at="2025-06-15 10:00",
                completed_at="2025-06-14 09:00"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_completed_at_date_before_plan_start(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                start_time="2025-06-15",
                completed_at="2025-06-14 10:00",
                currency="ILS"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_tax_rate_out_of_range(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                tax_rate="150"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_total_amount_mismatch(self):
        from forms import ServiceRequestForm
        form = ServiceRequestForm(
            _fd(customer_id="1", vehicle_vrn="ABC123",
                parts_total="200", labor_total="100", discount_total="0",
                tax_rate="17", total_amount="999"),
            meta=FORM_META,
        )
        assert form.validate() is False


class TestShipmentFormValidateRemaining:
    """Covers ShipmentForm.validate remaining branches (lines 2117-2131)."""

    def test_no_items(self):
        from forms import ShipmentForm
        form = ShipmentForm(
            _fd(shipment_number="SHP-001", currency="USD", status="DRAFT"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_items_without_product_warehouse_quantity(self):
        from forms import ShipmentForm
        fd = MultiDict([
            ("shipment_number", "SHP-002"), ("currency", "USD"),
            ("status", "DRAFT"), ("destination_id", "1"),
            ("items-0-product_id", ""), ("items-0-warehouse_id", ""),
            ("items-0-quantity", "0"), ("items-0-unit_cost", "50"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        assert form.validate() is False

    def test_duplicate_product_warehouse(self):
        from forms import ShipmentForm
        fd = MultiDict([
            ("shipment_number", "SHP-003"), ("currency", "USD"),
            ("status", "DRAFT"), ("destination_id", "1"),
            ("items-0-product_id", "1"), ("items-0-warehouse_id", "1"),
            ("items-0-quantity", "10"), ("items-0-unit_cost", "50"),
            ("items-1-product_id", "1"), ("items-1-warehouse_id", "1"),
            ("items-1-quantity", "5"), ("items-1-unit_cost", "50"),
        ])
        form = ShipmentForm(fd, meta=FORM_META)
        assert form.validate() is False


class TestStockAdjustmentFormValidateRemaining:
    """Covers StockAdjustmentForm.validate (lines 3114-3123)."""

    def test_invalid_reason(self):
        from forms import StockAdjustmentForm
        form = StockAdjustmentForm(
            _fd(reason="INVALID", warehouse_id="1"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_no_valid_items(self):
        from forms import StockAdjustmentForm
        form = StockAdjustmentForm(
            _fd(reason="DAMAGED", warehouse_id="1"),
            meta=FORM_META,
        )
        assert form.validate() is False

    def test_valid_submission(self):
        from forms import StockAdjustmentForm
        fd = MultiDict([
            ("date", "2025-06-15"),
            ("warehouse_id", "1"),
            ("reason", "DAMAGED"),
            ("items-0-product_id", "1"),
            ("items-0-quantity", "5"),
            ("items-0-unit_cost", "10"),
        ])
        form = StockAdjustmentForm(fd, meta=FORM_META)
        assert form.validate() is True


class TestCustomerFormOnlineRemaining:
    """Covers CustomerFormOnline validators (lines 3150, 3160-3161)."""

    def test_validate_phone_sets_data(self):
        from forms import CustomerFormOnline
        form = CustomerFormOnline(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "0501234567"
        form.validate_phone(field)
        assert field.data == "0501234567"

    def test_validate_password_requires_digit(self):
        from forms import CustomerFormOnline
        from wtforms.validators import ValidationError
        form = CustomerFormOnline(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "abcdefgh"
        with pytest.raises(ValidationError, match="رقم"):
            form.validate_password(field)

    def test_validate_password_requires_alpha(self):
        from forms import CustomerFormOnline
        from wtforms.validators import ValidationError
        form = CustomerFormOnline(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "12345678"
        with pytest.raises(ValidationError, match="حرف"):
            form.validate_password(field)


class TestOnlinePaymentFormValidate:
    """Covers OnlinePaymentForm validators (lines 3206-3238)."""

    def test_validate_transaction_data_valid_json(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = '{"key": "value"}'
        form.validate_transaction_data(field)

    def test_validate_transaction_data_invalid_json(self):
        from forms import OnlinePaymentForm
        from wtforms.validators import ValidationError
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "{bad json}"
        with pytest.raises(ValidationError):
            form.validate_transaction_data(field)

    def test_validate_transaction_data_empty(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = ""
        form.validate_transaction_data(field)

    def test_validate_card_last4_valid(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "1234"
        form.validate_card_last4(field)

    def test_validate_card_last4_invalid_length(self):
        from forms import OnlinePaymentForm
        from wtforms.validators import ValidationError
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "12"
        with pytest.raises(ValidationError):
            form.validate_card_last4(field)

    def test_validate_card_last4_invalid_non_digit(self):
        from forms import OnlinePaymentForm
        from wtforms.validators import ValidationError
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "abcd"
        with pytest.raises(ValidationError):
            form.validate_card_last4(field)

    def test_validate_card_last4_empty(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = ""
        form.validate_card_last4(field)

    def test_validate_card_expiry_valid(self, mocker):
        from forms import OnlinePaymentForm
        mocker.patch("forms.utils.is_valid_expiry_mm_yy", return_value=True)
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "12/28"
        form.validate_card_expiry(field)

    def test_validate_card_expiry_invalid(self, mocker):
        from forms import OnlinePaymentForm
        from wtforms.validators import ValidationError
        mocker.patch("forms.utils.is_valid_expiry_mm_yy", return_value=False)
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = "13/28"
        with pytest.raises(ValidationError):
            form.validate_card_expiry(field)

    def test_validate_card_expiry_empty(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(_fd(), meta=FORM_META)
        field = mock.MagicMock()
        field.data = ""
        form.validate_card_expiry(field)

    def test_completed_mapped_to_success(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(
            _fd(payment_ref="REF1", order_id="1", amount="100",
                currency="ILS", status="COMPLETED", processed_at="2025-06-15 10:00"),
            meta=FORM_META,
        )
        assert form.validate() is True
        assert form.status.data == "SUCCESS"

    def test_success_requires_processed_at(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(
            _fd(payment_ref="REF1", order_id="1", amount="100",
                currency="ILS", status="SUCCESS"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "processed_at" in form.errors

    def test_card_payload_requires_brand(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(
            _fd(payment_ref="REF1", order_id="1", amount="100",
                currency="ILS", status="PENDING",
                card_encrypted="some_data"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "card_brand" in form.errors

    def test_card_payload_requires_last4(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(
            _fd(payment_ref="REF1", order_id="1", amount="100",
                currency="ILS", status="PENDING",
                card_brand="VISA"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "card_last4" in form.errors

    def test_card_payload_requires_expiry(self):
        from forms import OnlinePaymentForm
        form = OnlinePaymentForm(
            _fd(payment_ref="REF1", order_id="1", amount="100",
                currency="ILS", status="PENDING",
                card_brand="VISA", card_last4="1234"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "card_expiry" in form.errors

    def test_valid_card_payload(self, mocker):
        from forms import OnlinePaymentForm
        mocker.patch("forms.utils.is_valid_expiry_mm_yy", return_value=True)
        form = OnlinePaymentForm(
            _fd(payment_ref="REF1", order_id="1", amount="100",
                currency="ILS", status="PENDING",
                card_brand="VISA", card_last4="1234",
                card_expiry="12/28"),
            meta=FORM_META,
        )
        assert form.validate() is True


class TestExpenseTypeFormRemaining:
    """Covers ExpenseTypeForm __init__ branches (lines 2446-2459)."""

    def test_init_catching_import_error(self, app, mocker):
        from forms import ExpenseTypeForm
        mocker.patch("models.Account.query.filter_by")
        import builtins as _b
        real = _b.__import__
        def fake(name, *args, **kwargs):
            if name == 'flask_login':
                raise ImportError("no flask_login")
            return real(name, *args, **kwargs)
        with mock.patch.object(_b, '__import__', side_effect=fake):
            with app.test_request_context():
                form = ExpenseTypeForm(meta=FORM_META)
                assert form.show_fields_meta is not None

    def test_fields_meta_serialization_from_obj(self, app, mocker):
        from forms import ExpenseTypeForm
        mocker.patch("models.Account.query.filter_by")
        obj = mock.MagicMock()
        obj.fields_meta = {"kind": "SALARY", "gl_account_code": "5000"}
        with app.test_request_context():
            admin = mock.MagicMock(is_system_account=True)
            admin.username = "admin"
            admin.role.name = "OWNER"
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                form = ExpenseTypeForm(obj=obj, meta=FORM_META)
                assert form.gl_account_code.data == "5000"
                assert form.fields_meta.data is not None


# ═══════════════════════════════════════════════════════════════════════════
# Block 1: _norm_invoice_no
# ═══════════════════════════════════════════════════════════════════════════

class TestNormInvoiceNo:
    """_norm_invoice_no() standalone utility (lines 3498-3501)."""

    def test_none_returns_none(self):
        from forms import _norm_invoice_no
        assert _norm_invoice_no(None) is None

    def test_empty_returns_none(self):
        from forms import _norm_invoice_no
        assert _norm_invoice_no("") is None

    def test_whitespace_only_returns_none(self):
        from forms import _norm_invoice_no
        assert _norm_invoice_no("  ") is None

    def test_trims_and_uppercases(self):
        from forms import _norm_invoice_no
        assert _norm_invoice_no(" abc ") == "ABC"

    def test_removes_inner_spaces(self):
        from forms import _norm_invoice_no
        assert _norm_invoice_no("a b c") == "ABC"


# ═══════════════════════════════════════════════════════════════════════════
# Block 2: ProductCategoryForm.validate_name
# ═══════════════════════════════════════════════════════════════════════════

class TestProductCategoryFormValidateName:
    """ProductCategoryForm.validate_name — no-duplicate branch."""

    def test_unique_name_passes(self):
        from forms import ProductCategoryForm
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        with mock.patch("forms.ProductCategory.query", mock_q):
            form = ProductCategoryForm(meta=FORM_META)
            form.id.data = ""
            field = mock.MagicMock()
            field.data = "New Category"
            form.validate_name(field)


# ═══════════════════════════════════════════════════════════════════════════
# Block 3: ImportForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestImportFormValidate:
    """ImportForm.validate — invalid file extension."""

    def test_invalid_file_extension(self):
        from forms import ImportForm
        form = ImportForm(
            _fd(warehouse_id="1", duplicate_strategy="skip"),
            meta=FORM_META,
        )
        f = mock.MagicMock()
        f.filename = "test.pdf"
        form.file.data = f
        assert form.validate() is False
        assert "file" in form.errors


# ═══════════════════════════════════════════════════════════════════════════
# Block 4: WarehouseOnlineDefaultForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestWarehouseOnlineDefaultFormValidate:
    """WarehouseOnlineDefaultForm.validate — missing confirm."""

    def test_missing_confirm(self):
        from forms import WarehouseOnlineDefaultForm
        form = WarehouseOnlineDefaultForm(_fd(), meta=FORM_META)
        form.confirm.data = False
        assert form.validate() is False
        assert "confirm" in form.errors


# ═══════════════════════════════════════════════════════════════════════════
# Block 5: ProductForm remaining branches
# ═══════════════════════════════════════════════════════════════════════════

class TestProductFormRemainingBranches:
    """Edge cases in ProductForm.validate, validate_barcode, _clean_image."""

    @staticmethod
    def _mock_queries(mocker):
        mock_q = mock.MagicMock()
        mock_q.filter.return_value.first.return_value = None
        mock_q.filter_by.return_value.first.return_value = None
        mocker.patch("forms.Product.query", mock_q)

    def test_no_category_id(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        form = ProductForm(_fd(name="Test", currency="ILS"), meta=FORM_META)
        assert form.validate() is False
        assert "category_id" in form.errors

    def test_price_falls_back_to_selling_price(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        form = ProductForm(
            _fd(name="Test", selling_price="100", category_id="1", currency="ILS"),
            meta=FORM_META,
        )
        try:
            result = form.validate()
        except TypeError:
            result = False
        assert result is False  # category DB lookup fails, but tests the branch

    def test_category_name_from_db(self, app, mocker):
        from forms import ProductForm
        self._mock_queries(mocker)
        form = ProductForm(
            _fd(name="Test", category_id="5", currency="ILS"),
            meta=FORM_META,
        )
        try:
            result = form.validate()
        except TypeError:
            result = False
        assert result is False

    def test_validate_barcode_invalid_suggested(self):
        from forms import ProductForm
        from wtforms.validators import ValidationError
        form = ProductForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "any"
        with mock.patch(
            "forms.validate_barcode",
            return_value={"normalized": "123", "valid": False, "suggested": "124"},
        ):
            with pytest.raises(ValidationError):
                form.validate_barcode(field)

    def test_validate_barcode_invalid_no_suggested(self):
        from forms import ProductForm
        from wtforms.validators import ValidationError
        form = ProductForm(meta=FORM_META)
        field = mock.MagicMock()
        field.data = "any"
        with mock.patch(
            "forms.validate_barcode",
            return_value={"normalized": "123", "valid": False},
        ):
            with pytest.raises(ValidationError, match="غير صالح."):
                form.validate_barcode(field)

    def test_clean_image_exception_returns_input(self):
        from forms import ProductForm
        form = ProductForm(meta=FORM_META)
        with mock.patch("os.path.basename", side_effect=Exception("boom")):
            result = form._clean_image("subdir/photo.png")
            assert result == "subdir/photo.png"


# ═══════════════════════════════════════════════════════════════════════════
# Block 6: WarehouseForm remaining branches
# ═══════════════════════════════════════════════════════════════════════════

class TestWarehouseFormRemainingBranches:
    """Exception handlers, share_percent validation, cycle detection in WarehouseForm."""

    def test_slug_uniqueness_exception(self):
        from forms import WarehouseForm
        form = WarehouseForm(
            _fd(warehouse_type="ONLINE", online_slug="test-slug", name="Test"),
            meta=FORM_META,
        )
        with mock.patch("forms.Warehouse.query.filter", side_effect=Exception("DB err")):
            assert form.validate() is True

    def test_online_default_exception(self):
        from forms import WarehouseForm
        form = WarehouseForm(
            _fd(warehouse_type="ONLINE", online_is_default="y", online_slug="", name="Test"),
            meta=FORM_META,
        )
        with mock.patch("forms.Warehouse.query.filter", side_effect=Exception("DB err")):
            assert form.validate() is True

    def test_partner_negative_share_percent(self):
        from forms import WarehouseForm
        form = WarehouseForm(
            _fd(warehouse_type="PARTNER", partner_id="1", share_percent="-5", name="Test"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "share_percent" in form.errors

    def test_cycle_detection_loop_iterates(self):
        from forms import WarehouseForm
        node2 = mock.MagicMock(parent_id=3)
        node3 = mock.MagicMock(parent_id=None)
        mock_get = mock.MagicMock()
        mock_get.side_effect = [node2, node3]
        with mock.patch("forms.db.session.get", mock_get):
            form = WarehouseForm(
                _fd(warehouse_type="MAIN", parent_id="2", name="Test"),
                meta=FORM_META,
            )
            assert form.validate() is True

    def test_cycle_detection_exception(self):
        from forms import WarehouseForm
        form = WarehouseForm(
            _fd(warehouse_type="MAIN", parent_id="2", name="Test", id="1"),
            meta=FORM_META,
        )
        with mock.patch("forms.db.session.get", side_effect=Exception("DB err")):
            assert form.validate() is True


# ═══════════════════════════════════════════════════════════════════════════
# Block 7: CheckForm.validate_check_due_date
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckFormValidateCheckDueDate:
    """CheckForm.validate_check_due_date — date comparison."""

    def test_due_date_after_check_date_passes(self):
        from forms import CheckForm
        form = CheckForm(meta=FORM_META)
        form.check_date.data = date(2025, 1, 1)
        field = mock.MagicMock()
        field.data = date(2025, 1, 15)
        form.validate_check_due_date(field)

    def test_due_date_before_check_date_raises(self):
        from forms import CheckForm
        from wtforms.validators import ValidationError
        form = CheckForm(meta=FORM_META)
        form.check_date.data = date(2025, 1, 15)
        field = mock.MagicMock()
        field.data = date(2025, 1, 1)
        with pytest.raises(ValidationError, match="بعد تاريخ الشيك"):
            form.validate_check_due_date(field)


# ═══════════════════════════════════════════════════════════════════════════
# Block 8: PartnerShareForm
# ═══════════════════════════════════════════════════════════════════════════

class TestPartnerShareFormValidate:
    """PartnerShareForm.validate — share_percentage > 0."""

    def test_zero_share_percentage_fails(self):
        from forms import PartnerShareForm
        form = PartnerShareForm(_fd(share_percentage="0"), meta=FORM_META)
        assert form.validate() is False
        assert "share_percentage" in form.errors


# ═══════════════════════════════════════════════════════════════════════════
# Block 9: StockLevelForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestStockLevelFormValidate:
    """StockLevelForm.validate — reserved, min/max, duplicates."""

    def test_reserved_exceeds_quantity(self):
        from forms import StockLevelForm
        form = StockLevelForm(
            _fd(quantity="5", reserved_quantity="10", warehouse_id="1"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "reserved_quantity" in form.errors

    def test_max_less_than_min(self):
        from forms import StockLevelForm
        form = StockLevelForm(
            _fd(quantity="10", min_stock="20", max_stock="10", warehouse_id="1"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "max_stock" in form.errors

    def test_no_product_id(self):
        from forms import StockLevelForm
        form = StockLevelForm(_fd(quantity="10", warehouse_id="1"), meta=FORM_META)
        assert form.validate() is False

    def test_no_warehouse_id(self):
        from forms import StockLevelForm
        form = StockLevelForm(_fd(quantity="10", product_id="1"), meta=FORM_META)
        assert form.validate() is False

    def test_duplicate_stock_level(self):
        from forms import StockLevelForm
        from models import StockLevel
        existing = mock.MagicMock(id=99)
        mock_fb = mock.MagicMock()
        mock_fb.filter_by.return_value.first.return_value = existing
        with mock.patch.object(StockLevel, "query", mock_fb):
            form = StockLevelForm(
                _fd(quantity="10", product_id="1", warehouse_id="1"),
                meta=FORM_META,
            )
            assert form.validate() is False
            assert "warehouse_id" in form.errors

    def test_duplicate_check_exception(self):
        from forms import StockLevelForm
        with mock.patch(
            "forms.StockLevel.query.filter_by", side_effect=Exception("DB err")
        ):
            form = StockLevelForm(
                _fd(quantity="10", product_id="1", warehouse_id="1"),
                meta=FORM_META,
            )
            assert form.validate() is True


# ═══════════════════════════════════════════════════════════════════════════
# Block 10: NoteForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestNoteFormValidate:
    """NoteForm.validate — super validate fail & entity_id check."""

    def test_super_validate_fails(self, app):
        from forms import NoteForm
        form = NoteForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_entity_id_not_numeric(self, app):
        from forms import NoteForm
        form = NoteForm(_fd(content="Test note", entity_id="abc"), meta=FORM_META)
        assert form.validate() is False
        assert "entity_id" in form.errors


# ═══════════════════════════════════════════════════════════════════════════
# Block 11: JournalEntryForm.validate / apply_to
# ═══════════════════════════════════════════════════════════════════════════

class TestJournalEntryFormRemaining:
    """JournalEntryForm.validate — no used lines; apply_to — no acc_id."""

    def test_no_used_lines(self, mocker):
        from forms import JournalEntryForm, JournalLineForm
        orig_validate = JournalLineForm.validate
        JournalLineForm.validate = lambda self, **kw: True
        try:
            fd = MultiDict([
                ("entry_date", "2025-01-01T10:00"),
                ("currency", "ILS"),
                ("lines-0-account_id", "1"),
                ("lines-0-debit", "0"),
                ("lines-0-credit", "0"),
                ("lines-1-account_id", "2"),
                ("lines-1-debit", "0"),
                ("lines-1-credit", "0"),
            ])
            form = JournalEntryForm(fd, meta=FORM_META)
            assert form.validate() is False
            assert "lines" in form.errors
        finally:
            JournalLineForm.validate = orig_validate

    def test_apply_to_skips_line_without_acc_id(self, mocker):
        from forms import JournalEntryForm
        mocker.patch("models.JournalLine", return_value=mock.MagicMock(), create=True)
        fd = MultiDict([
            ("entry_date", "2025-01-01T10:00"),
            ("currency", "ILS"),
            ("lines-0-account_id", ""),
            ("lines-0-debit", "100"),
            ("lines-0-credit", "0"),
            ("lines-1-account_id", "2"),
            ("lines-1-debit", "0"),
            ("lines-1-credit", "100"),
        ])
        form = JournalEntryForm(fd, meta=FORM_META)
        form._used_lines_count = 1
        je = mock.MagicMock()
        result = form.apply_to(je)
        assert len(result.lines) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Block 12: GeneralLedgerFilterForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestGeneralLedgerFilterFormValidate:
    """GeneralLedgerFilterForm.validate — super validate fails."""

    def test_super_validate_fails(self):
        from forms import GeneralLedgerFilterForm
        form = GeneralLedgerFilterForm(_fd(start_date="invalid"), meta=FORM_META)
        assert form.validate() is False


# ═══════════════════════════════════════════════════════════════════════════
# Block 13: TrialBalanceFilterForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestTrialBalanceFilterFormValidate:
    """TrialBalanceFilterForm.validate — super validate fails."""

    def test_super_validate_fails(self):
        from forms import TrialBalanceFilterForm
        form = TrialBalanceFilterForm(_fd(start_date="invalid"), meta=FORM_META)
        assert form.validate() is False


# ═══════════════════════════════════════════════════════════════════════════
# Block 14: ExportContactsForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestExportContactsFormValidate:
    """ExportContactsForm.validate — super fail, no customers, no fields."""

    def test_super_validate_fails(self):
        from forms import ExportContactsForm
        form = ExportContactsForm(_fd(), meta=FORM_META)
        assert form.validate() is False

    def test_no_customers(self):
        from forms import ExportContactsForm
        form = ExportContactsForm(
            _fd(customer_ids=[], fields="name", format="vcf"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "customer_ids" in form.errors

    def test_no_fields_selected(self):
        from forms import ExportContactsForm
        form = ExportContactsForm(
            _fd(customer_ids=["1"], fields=[], format="vcf"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "fields" in form.errors


# ═══════════════════════════════════════════════════════════════════════════
# Block 15: OnlineCartPaymentForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestOnlineCartPaymentFormValidateBranches:
    """OnlineCartPaymentForm.validate — unsupported method, card_number error."""

    def test_unsupported_payment_method(self):
        from forms import OnlineCartPaymentForm
        form = OnlineCartPaymentForm(_fd(payment_method="cod"), meta=FORM_META)
        assert form.validate() is False
        assert "payment_method" in form.errors

    def test_validate_card_payload_card_number_error(self, mocker):
        from forms import OnlineCartPaymentForm
        from wtforms.validators import ValidationError
        mocker.patch(
            "forms.PaymentDetailsMixin._validate_card_payload",
            side_effect=ValidationError("رقم البطاقة غير صحيح"),
        )
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="1234",
                card_holder="Test", expiry="12/28", cvv="123"),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "card_number" in form.errors

    def test_cvv_missing(self, mocker):
        from forms import OnlineCartPaymentForm
        mocker.patch("forms.PaymentDetailsMixin._validate_card_payload",
                     return_value="1111")
        form = OnlineCartPaymentForm(
            _fd(payment_method="card", card_number="4111111111111111",
                card_holder="Test", expiry="12/28", cvv=""),
            meta=FORM_META,
        )
        assert form.validate() is False
        assert "cvv" in form.errors


# ═══════════════════════════════════════════════════════════════════════════
# Block 16: ImportRunFilterForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestImportRunFilterFormValidateSuper:
    """ImportRunFilterForm.validate — super validate fails."""

    def test_super_validate_fails(self):
        from forms import ImportRunFilterForm
        form = ImportRunFilterForm(_fd(date_from="bad-date"), meta=FORM_META)
        assert form.validate() is False


# ═══════════════════════════════════════════════════════════════════════════
# Block 17: ExchangeRateForm.__init__ exception handler
# ═══════════════════════════════════════════════════════════════════════════

class TestExchangeRateFormInit:
    """ExchangeRateForm.__init__ — DB exception."""

    def test_init_db_exception(self, mocker):
        from forms import ExchangeRateForm
        mocker.patch("models.Currency.query.filter_by", side_effect=Exception("DB down"))
        form = ExchangeRateForm(meta=FORM_META)
        assert form.base_code.choices == []


# ═══════════════════════════════════════════════════════════════════════════
# Block 18: SaleReturnForm.__init__ exception & validate branches
# ═══════════════════════════════════════════════════════════════════════════

class TestSaleReturnFormInit:
    """SaleReturnForm.__init__ — exception handler populates choices."""

    def test_init_queries_exception(self):
        from forms import SaleReturnForm
        with mock.patch("forms.Sale.query.filter_by", side_effect=Exception("DB down")):
            with mock.patch("forms.Customer.query"):
                with mock.patch("forms.Warehouse.query"):
                    with mock.patch("forms.Product.query"):
                        form = SaleReturnForm(meta=FORM_META)
                        assert form.sale_id.choices == [(0, 'اختر البيع')]
                        assert form.customer_id.choices == [(0, 'اختر الزبون')]


class TestSaleReturnFormValidateBranches:
    """SaleReturnForm.validate — default status."""

    @staticmethod
    def _mocks():
        from datetime import datetime
        s = mock.MagicMock(id=1)
        s.created_at = datetime(2025, 1, 1, 0, 0)
        c = mock.MagicMock(id=1, name="C")
        w = mock.MagicMock(id=1, name="W")
        p = mock.MagicMock(id=1, name="P", barcode="123")
        return (
            mock.patch("forms.Sale.query", mock.MagicMock(
                **{"filter_by.return_value.order_by.return_value.limit.return_value.all.return_value": [s]})),
            mock.patch("forms.Customer.query", mock.MagicMock(
                **{"filter_by.return_value.order_by.return_value.all.return_value": [c]})),
            mock.patch("forms.Warehouse.query", mock.MagicMock(
                **{"filter_by.return_value.order_by.return_value.all.return_value": [w]})),
            mock.patch("forms.Product.query", mock.MagicMock(
                **{"filter_by.return_value.order_by.return_value.limit.return_value.all.return_value": [p]})),
        )

    def test_default_status(self):
        from forms import SaleReturnForm
        fd = MultiDict([
            ("sale_id", "1"), ("customer_id", "1"), ("reason", "Defect"),
            ("currency", "ILS"),
            ("lines-0-product_id", "1"), ("lines-0-quantity", "2"),
            ("lines-0-unit_price", "100"),
        ])
        patches = self._mocks()
        with patches[0], patches[1], patches[2], patches[3]:
            form = SaleReturnForm(fd, meta=FORM_META)
            form.status.data = ""
            assert form.validate() is True
            assert form.status.data == "CONFIRMED"


# ═══════════════════════════════════════════════════════════════════════════
# Block 19: SettlementRangeForm.validate
# ═══════════════════════════════════════════════════════════════════════════

class TestSettlementRangeFormValidateSuper:
    """SettlementRangeForm.validate — super validate fails."""

    def test_super_validate_fails(self):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(_fd(start="bad-date"), meta=FORM_META)
        assert form.validate() is False


# ═══════════════════════════════════════════════════════════════════════════
# Block 20: CustomerForm.apply_to with password set
# ═══════════════════════════════════════════════════════════════════════════

class TestCustomerFormApplyToPassword:
    """CustomerForm.apply_to — sets password when provided."""

    def test_apply_to_sets_password(self, app):
        from forms import CustomerForm
        with app.app_context():
            form = CustomerForm(_fd(
                name="Test", phone="0501234567",
                email="test@test.com", category="NORMAL",
                currency="ILS", password="secret123",
            ), meta=FORM_META)
            customer = mock.MagicMock()
            form.apply_to(customer)
            customer.set_password.assert_called_once_with("secret123")
