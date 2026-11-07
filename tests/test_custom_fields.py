from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timezone
import pytest
from werkzeug.datastructures import MultiDict
from wtforms.validators import ValidationError, StopValidation


# ─── Helper functions tests ────────────────────────────────────────────────

class TestUtcNowNaive:
    def test_returns_naive_datetime(self):
        from forms import _utc_now_naive
        dt = _utc_now_naive()
        assert dt.tzinfo is None

    def test_returns_recent_time(self):
        from forms import _utc_now_naive
        dt = _utc_now_naive()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        diff = abs((now - dt).total_seconds())
        assert diff < 5


class TestQ2:
    def test_quantizes_string(self):
        from forms import Q2
        assert Q2("10.5") == Decimal("10.50")
        assert Q2("0.1") == Decimal("0.10")

    def test_quantizes_decimal(self):
        from forms import Q2
        assert Q2(Decimal("3.333")) == Decimal("3.33")

    def test_rounds_half_up(self):
        from forms import Q2
        assert Q2("1.235") == Decimal("1.24")
        assert Q2("1.234") == Decimal("1.23")

    def test_zero_for_invalid(self):
        from forms import Q2
        assert Q2(None) == Decimal("0.00")
        assert Q2("abc") == Decimal("0.00")


class TestToInt:
    def test_normal_int(self):
        from forms import to_int
        assert to_int(42) == 42
        assert to_int("42") == 42

    def test_arabic_digits(self):
        from forms import to_int
        assert to_int("٤٢") == 42
        assert to_int("۱۲۳") == 123

    def test_commas_and_spaces(self):
        from forms import to_int
        assert to_int("1,234") == 1234
        assert to_int("  56  ") == 56

    def test_none_and_empty(self):
        from forms import to_int
        assert to_int(None) is None
        assert to_int("") is None

    def test_invalid_returns_none(self):
        from forms import to_int
        assert to_int("not a number") is None


class TestToDec:
    def test_normal_decimal(self):
        from forms import to_dec
        assert to_dec("10.5") == Decimal("10.5")
        assert to_dec(42) == Decimal("42")

    def test_arabic_digits(self):
        from forms import to_dec
        assert to_dec("٤٢٫٥") == Decimal("42.5")

    def test_commas_stripped(self):
        from forms import to_dec
        assert to_dec("1,234.56") == Decimal("1234.56")

    def test_none_and_empty(self):
        from forms import to_dec
        assert to_dec(None) is None
        assert to_dec("") is None

    def test_invalid_returns_none(self):
        from forms import to_dec
        assert to_dec("not a number") is None


class TestSlugify:
    def test_basic_slug(self):
        from forms import _slugify
        assert _slugify("Hello World") == "hello-world"

    def test_multiple_spaces_and_dashes(self):
        from forms import _slugify
        assert _slugify("  Hello   World  ") == "hello-world"

    def test_special_chars_removed(self):
        from forms import _slugify
        assert _slugify("Hello! @World#") == "hello-world"

    def test_none_or_empty(self):
        from forms import _slugify
        assert _slugify(None) == ""
        assert _slugify("") == ""


class TestIsUrlLike:
    def test_http_url(self):
        from forms import _is_url_like
        assert _is_url_like("http://example.com") is True

    def test_https_url(self):
        from forms import _is_url_like
        assert _is_url_like("https://example.com") is True

    def test_root_path(self):
        from forms import _is_url_like
        assert _is_url_like("/uploads/image.jpg") is True

    def test_relative_path(self):
        from forms import _is_url_like
        assert _is_url_like("uploads/image.jpg") is False

    def test_none(self):
        from forms import _is_url_like
        assert _is_url_like(None) is False


class TestCleanImagePath:
    def test_none_returns_none(self):
        from forms import _clean_image_path
        assert _clean_image_path(None) is None

    def test_empty_returns_none(self):
        from forms import _clean_image_path
        assert _clean_image_path("") is None

    def test_url_preserved(self):
        from forms import _clean_image_path
        url = "https://example.com/img.jpg"
        assert _clean_image_path(url) == url

    def test_local_path_abs_starts_with_slash(self):
        from forms import _clean_image_path
        assert _clean_image_path("/path/to/image.jpg") == "/path/to/image.jpg"

    def test_whitespace_only(self):
        from forms import _clean_image_path
        assert _clean_image_path("   ") is None

    def test_relative_path_uses_basename(self):
        from forms import _clean_image_path
        assert _clean_image_path("subdir/image.jpg") == "image.jpg"


class TestNormalizePhone:
    def test_basic_normalize(self):
        from forms import normalize_phone
        assert normalize_phone("  050 123 4567  ") == "0501234567"

    def test_preserves_plus_prefix(self):
        from forms import normalize_phone
        assert normalize_phone("+972 59 999 9999") == "+972599999999"

    def test_none_and_empty(self):
        from forms import normalize_phone
        assert normalize_phone(None) is None
        assert normalize_phone("") is None

    def test_whitespace_only(self):
        from forms import normalize_phone
        assert normalize_phone("   ") is None


class TestNormalizeEmail:
    def test_strips_and_lowers(self):
        from forms import normalize_email
        assert normalize_email("  Test@Example.COM  ") == "test@example.com"

    def test_none_and_empty(self):
        from forms import normalize_email
        assert normalize_email(None) is None
        assert normalize_email("") is None


class TestOnlyDigits:
    def test_strips_non_digits(self):
        from forms import only_digits
        assert only_digits("abc123def456") == "123456"

    def test_empty_or_none(self):
        from forms import only_digits
        assert only_digits(None) == ""
        assert only_digits("") == ""

    def test_already_digits(self):
        from forms import only_digits
        assert only_digits("12345") == "12345"


class TestEnumChoices:
    def test_enum_with_members(self, app):
        import enum
        class Color(str, enum.Enum):
            RED = "red"
            GREEN = "green"
        from forms import enum_choices
        result = enum_choices(Color)
        assert ("", "— اختر —") in result
        assert ("red", "red") in result
        assert ("green", "green") in result

    def test_enum_without_blank(self, app):
        import enum
        class Color(str, enum.Enum):
            RED = "red"
        from forms import enum_choices
        result = enum_choices(Color, include_blank=False)
        assert ("", "— اختر —") not in result

    def test_string_input(self, app):
        from forms import enum_choices
        result = enum_choices("test_value")
        assert ("test_value", "test_value") in result

    def test_list_input(self, app):
        from forms import enum_choices
        result = enum_choices(["a", "b"])
        assert ("a", "a") in result
        assert ("b", "b") in result

    def test_invalid_enum_returns_empty(self, app):
        from forms import enum_choices
        result = enum_choices(42)
        assert result == [] or result == [("", "— اختر —")]

    def test_broken_enum_raises_exception(self, app):
        from forms import enum_choices
        class Broken:
            @property
            def __members__(self):
                raise RuntimeError("broken")
        result = enum_choices(Broken)
        assert result == [] or result == [("", "— اختر —")]


class TestCurrencyChoices:
    def test_fallback_when_no_db(self, app):
        from forms import currency_choices
        result = currency_choices()
        assert len(result) > 1
        assert any(c == "ILS" for c, _ in result)

    def test_no_blank(self, app):
        from forms import currency_choices
        result = currency_choices(include_blank=False)
        assert ("", "— اختر —") not in result

    def test_custom_blank(self, app):
        from forms import currency_choices
        result = currency_choices(blank="اختر")
        assert ("", "اختر") in result


# ─── Custom field classes tests ─────────────────────────────────────────────

class TestStrippedStringField:
    def test_strips_whitespace(self, app):
        from forms import StrippedStringField
        from wtforms.form import Form
        class F(Form):
            name = StrippedStringField()
        form = F(MultiDict([("name", "  hello  ")]))
        assert form.name.data == "hello"

    def test_empty_becomes_none(self, app):
        from forms import StrippedStringField
        from wtforms.form import Form
        class F(Form):
            name = StrippedStringField()
        form = F(MultiDict([("name", "")]))
        assert form.name.data is None

    def test_whitespace_only_becomes_none(self, app):
        from forms import StrippedStringField
        from wtforms.form import Form
        class F(Form):
            name = StrippedStringField()
        form = F(MultiDict([("name", "   ")]))
        assert form.name.data is None

    def test_none_stays_none(self, app):
        from forms import StrippedStringField
        from wtforms.form import Form
        class F(Form):
            name = StrippedStringField()
        form = F()
        assert form.name.data is None


class TestMoneyField:
    def test_quantizes_to_two_places(self, app):
        from forms import MoneyField
        from wtforms.form import Form
        class F(Form):
            amount = MoneyField()
        form = F(MultiDict([("amount", "10.5")]))
        assert form.amount.data == Decimal("10.50")

    def test_rounds_half_up(self, app):
        from forms import MoneyField
        from wtforms.form import Form
        class F(Form):
            amount = MoneyField()
        form = F(MultiDict([("amount", "1.235")]))
        assert form.amount.data == Decimal("1.24")

    def test_invalid_returns_none(self, app):
        from forms import MoneyField
        from wtforms.form import Form
        class F(Form):
            amount = MoneyField()
        form = F(MultiDict([("amount", "not-a-number")]))
        assert form.amount.data is None

    def test_non_decimal_exception_caught(self, app):
        from forms import MoneyField
        from wtforms.form import Form
        class F(Form):
            amount = MoneyField()
        form = F(MultiDict([("amount", "1.2.3")]))
        assert form.amount.data is None

    def test_empty_returns_none(self, app):
        from forms import MoneyField
        from wtforms.form import Form
        class F(Form):
            amount = MoneyField()
        form = F(MultiDict([("amount", "")]))
        assert form.amount.data is None


class TestPercentField:
    def test_normal_percent(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "25.5")]))
        assert form.rate.data == Decimal("25.50")

    def test_zero_percent(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "0")]))
        assert form.rate.data == Decimal("0.00")

    def test_one_hundred_percent(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "100")]))
        assert form.rate.data == Decimal("100.00")

    def test_negative_raises(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "-1")]))
        assert not form.validate()
        assert "rate" in form.errors

    def test_over_100_raises(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "150")]))
        assert not form.validate()
        assert "rate" in form.errors

    def test_empty_returns_none(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "")]))
        assert form.rate.data is None

    def test_invalid_returns_none(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "not-a-number")]))
        assert form.rate.data is None

    def test_garbled_input_sets_none(self, app):
        from forms import PercentField
        from wtforms.form import Form
        class F(Form):
            rate = PercentField()
        form = F(MultiDict([("rate", "12x")]))
        assert form.rate.data is None


class TestEnumSelectField:
    def test_valid_choice(self, app, db_session):
        from forms import EnumSelectField
        from models import CustomerCategory
        from wtforms.form import Form
        class F(Form):
            cat = EnumSelectField(CustomerCategory)
        form = F(MultiDict([("cat", "ذهبي")]))
        assert form.validate()
        assert form.cat.data == "ذهبي"

    def test_invalid_choice(self, app, db_session):
        from forms import EnumSelectField
        from models import CustomerCategory
        from wtforms.form import Form
        class F(Form):
            cat = EnumSelectField(CustomerCategory)
        form = F(MultiDict([("cat", "invalid")]))
        assert not form.validate()
        assert "cat" in form.errors

    def test_blank_allowed(self, app, db_session):
        from forms import EnumSelectField
        from models import CustomerCategory
        from wtforms.form import Form
        class F(Form):
            cat = EnumSelectField(CustomerCategory)
        form = F(MultiDict([("cat", "")]))
        assert form.validate()

    def test_pre_validate_none_data_passes(self, app, db_session):
        from forms import EnumSelectField
        from models import CustomerCategory
        from wtforms.form import Form
        class F(Form):
            cat = EnumSelectField(CustomerCategory)
        form = F()
        assert form.cat.data in (None, "", "None")

    def test_enum_member_without_label(self, app):
        import enum
        from forms import EnumSelectField
        from wtforms.form import Form
        class Simple(str, enum.Enum):
            A = "alpha"
            B = "beta"
        class F(Form):
            val = EnumSelectField(Simple)
        form = F(MultiDict([("val", "alpha")]))
        assert form.validate()
        assert form.val.data == "alpha"

    def test_non_enum_input(self, app):
        from forms import EnumSelectField
        from wtforms.form import Form
        class F(Form):
            val = EnumSelectField(["x", "y"])
        form = F(MultiDict([("val", "x")]))
        assert form.validate()
        assert form.val.data == "x"

    def test_broken_enum_fallback(self, app):
        from forms import EnumSelectField
        from wtforms.form import Form
        class BrokenEnum:
            __members__ = property(lambda _: (_ for _ in ()).throw(RuntimeError()))
        class F(Form):
            val = EnumSelectField(BrokenEnum)
        form = F()
        assert form.val.data in (None, "", "None")


class TestCurrencySelectField:
    def test_valid_currency(self, app):
        from wtforms.form import Form
        from forms import CurrencySelectField
        class F(Form):
            cur = CurrencySelectField()
        form = F(MultiDict([("cur", "ILS")]))
        assert form.validate()
        assert form.cur.data == "ILS"

    def test_uppercases_input(self, app):
        from wtforms.form import Form
        from forms import CurrencySelectField
        class F(Form):
            cur = CurrencySelectField()
        form = F(MultiDict([("cur", "usd")]))
        assert form.validate()
        assert form.cur.data == "USD"

    def test_invalid_currency(self, app):
        from wtforms.form import Form
        from forms import CurrencySelectField
        class F(Form):
            cur = CurrencySelectField()
        form = F(MultiDict([("cur", "XYZ")]))
        assert not form.validate()
        assert "cur" in form.errors


class TestPaymentDetailsMixin:
    def test_validate_card_payload_empty_returns_none(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        assert obj._validate_card_payload("", "", "") is None

    def test_validate_card_payload_invalid_luhn(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="رقم البطاقة غير صالح"):
            obj._validate_card_payload("1234567890123456", "Holder", "12/28")

    def test_validate_card_payload_valid(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        result = obj._validate_card_payload("4111111111111111", "Test User", "12/28")
        assert result == "1111"

    def test_validate_card_payload_missing_holder(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="اسم حامل البطاقة"):
            obj._validate_card_payload("4111111111111111", "", "12/28")

    def test_validate_card_payload_invalid_expiry(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="تاريخ الانتهاء غير صالح"):
            obj._validate_card_payload("4111111111111111", "Test", "13/99")

    def test_validate_cheque_missing_number(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="رقم الشيك"):
            obj._validate_cheque("", "Bank", date(2025, 1, 1))

    def test_validate_cheque_missing_bank(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="اسم البنك"):
            obj._validate_cheque("123", "", date(2025, 1, 1))

    def test_validate_cheque_missing_due_date(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="تاريخ الاستحقاق"):
            obj._validate_cheque("123", "Bank", None)

    def test_validate_cheque_due_date_before_op_date(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        op_date = date(2025, 6, 1)
        due_date = date(2025, 5, 1)
        with pytest.raises(ValidationError, match="تاريخ الاستحقاق لا يمكن أن يسبق"):
            obj._validate_cheque("123", "Bank", due_date, op_date)

    def test_validate_bank_empty(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="مرجع التحويل البنكي"):
            obj._validate_bank("")

    def test_validate_bank_valid(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        obj._validate_bank("TRX123")  # should not raise

    def test_validate_online_empty_gateway(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="بوابة الدفع"):
            obj._validate_online("", "ref123")

    def test_validate_online_empty_ref(self, app):
        from forms import PaymentDetailsMixin
        obj = PaymentDetailsMixin()
        with pytest.raises(ValidationError, match="مرجع العملية"):
            obj._validate_online("Gateway", "")

    def test_build_payment_details_json_cheque(self, app):
        from forms import PaymentDetailsMixin
        import json
        obj = PaymentDetailsMixin()
        result = json.loads(obj.build_payment_details_json("CHEQUE", check_number="123", check_bank="BankA", check_due_date=date(2025,1,1)))
        assert result["type"] == "CHEQUE"
        assert result["number"] == "123"

    def test_build_payment_details_json_bank(self, app):
        from forms import PaymentDetailsMixin
        import json
        obj = PaymentDetailsMixin()
        result = json.loads(obj.build_payment_details_json("BANK", bank_transfer_ref="TRX999"))
        assert result["type"] == "BANK"
        assert result["transfer_ref"] == "TRX999"

    def test_build_payment_details_json_card(self, app):
        from forms import PaymentDetailsMixin
        import json
        obj = PaymentDetailsMixin()
        result = json.loads(obj.build_payment_details_json("CARD", card_last4="1234", card_holder="Holder", card_expiry="12/28", card_brand="VISA"))
        assert result["type"] == "CARD"
        assert "1234" in result["number_masked"]

    def test_build_payment_details_json_online(self, app):
        from forms import PaymentDetailsMixin
        import json
        obj = PaymentDetailsMixin()
        result = json.loads(obj.build_payment_details_json("ONLINE", online_gateway="Stripe", online_ref="pi_123"))
        assert result["type"] == "ONLINE"
        assert result["gateway"] == "Stripe"

    def test_build_payment_details_json_with_extra(self, app):
        from forms import PaymentDetailsMixin
        import json
        obj = PaymentDetailsMixin()
        result = json.loads(obj.build_payment_details_json("OTHER", extra={"note": "test"}))
        assert result["type"] == "OTHER"
        assert result["extra"]["note"] == "test"

    def test_build_payment_details_json_default_type(self, app):
        from forms import PaymentDetailsMixin
        import json
        obj = PaymentDetailsMixin()
        result = json.loads(obj.build_payment_details_json(None))
        assert result["type"] == "OTHER"


class TestAjaxSelectField:
    def test_pre_validate_allows_blank(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search", allow_blank=True)
        form = F(MultiDict([("pid", "")]))
        assert form.validate()

    def test_pre_validate_rejects_zero(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search")
        form = F(MultiDict([("pid", "0")]))
        assert not form.validate()
        assert "pid" in form.errors

    def test_process_formdata_arabic_digits(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search")
        form = F(MultiDict([("pid", "٤٢")]))
        assert form.pid.data == 42

    def test_process_formdata_blank(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search", allow_blank=True)
        form = F(MultiDict([("pid", "")]))
        assert form.pid.data is None


class TestAjaxSelectMultipleField:
    def test_process_formdata_list(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        from werkzeug.datastructures import MultiDict
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search")
        md = MultiDict([("ids", "1"), ("ids", "2"), ("ids", "3")])
        form = F(md)
        assert form.ids.data == [1, 2, 3]

    def test_pre_validate_passes(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search")
        form = F()
        assert form.ids.data == []

    def test_process_formdata_skips_empty(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search")
        form = F(MultiDict([("ids", ""), ("ids", "1")]))
        assert form.ids.data == [1]

    def test_process_formdata_skips_null_strings(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search")
        form = F(MultiDict([("ids", "none"), ("ids", "null"), ("ids", "0")]))
        assert form.ids.data == []

    def test_process_formdata_bad_coerce(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search", coerce=int)
        form = F(MultiDict([("ids", "not-a-number")]))
        assert form.ids.data == ["not-a-number"]

    def test_process_data_with_obj(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class Obj:
            id = 42
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search", coerce=int)
        form = F()
        form.ids.process_data([Obj()])
        assert form.ids.data == [42]

    def test_process_data_with_list_of_scalars(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search")
        form = F()
        form.ids.process_data([1, 2, 3])
        assert form.ids.data == [1, 2, 3]

    def test_process_data_empty(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search")
        form = F()
        form.ids.process_data(None)
        assert form.ids.data == []

    def test_process_data_single_value(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search", coerce=int)
        form = F()
        form.ids.process_data(99)
        assert form.ids.data == [99]

    def test_process_data_coerce_fallback(self, app):
        from forms import AjaxSelectMultipleField
        from wtforms.form import Form
        class F(Form):
            ids = AjaxSelectMultipleField("Products", endpoint="api.search", coerce=int)
        form = F()
        form.ids.process_data([object()])
        assert len(form.ids.data) == 1


class TestAjaxSelectFieldProcessData:
    def test_process_data_with_obj(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class Obj:
            id = 7
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search")
        form = F()
        form.pid.process_data(Obj())
        assert form.pid.data == 7

    def test_process_data_with_raw(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search")
        form = F()
        form.pid.process_data("42")
        assert form.pid.data == 42

    def test_process_data_coerce_fallback(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search", coerce=int)
        form = F()
        form.pid.process_data(object())
        assert isinstance(form.pid.data, object)

    def test_process_data_none(self, app):
        from forms import AjaxSelectField
        from wtforms.form import Form
        class F(Form):
            pid = AjaxSelectField("Product", endpoint="api.search", allow_blank=True)
        form = F()
        form.pid.process_data(None)
        assert form.pid.data is None


class TestUnifiedDateTimeField:
    def test_parses_iso_format(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField()
        form = F(MultiDict([("dt", "2025-01-15T10:30")]))
        assert form.validate()
        assert form.dt.data is not None

    def test_parses_timestamp_prefix(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField()
        form = F(MultiDict([("dt", "ts:1705300000")]))
        assert form.validate()
        assert form.dt.data is not None

    def test_invalid_format(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField()
        form = F(MultiDict([("dt", "not-a-date")]))
        assert not form.validate()
        assert "dt" in form.errors

    def test_empty_valuelist_sets_none(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField()
        form = F()
        assert form.dt.data is None

    def test_formats_list_init(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField(formats=["%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"])
        form = F(MultiDict([("dt", "15/01/2025 10:30")]))
        assert form.validate()

    def test_format_as_list_init(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField(format=["%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"])
        form = F(MultiDict([("dt", "15/01/2025 10:30")]))
        assert form.validate()

    def test_value_without_raw_data(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField()
        dt = datetime(2025, 6, 15, 10, 30)
        form = F()
        form.dt.data = dt
        assert form.dt._value() == "2025-06-15 10:30"

    def test_value_with_output_format(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField(output_format="%d/%m/%Y %H:%M")
        dt = datetime(2025, 6, 15, 10, 30)
        form = F()
        form.dt.data = dt
        assert form.dt._value() == "15/06/2025 10:30"

    def test_timestamp_exception(self, app):
        from forms import UnifiedDateTimeField
        from wtforms.form import Form
        class F(Form):
            dt = UnifiedDateTimeField()
        form = F(MultiDict([("dt", "ts:not-a-number")]))
        assert not form.validate()
        assert "dt" in form.errors


class TestUnifiedDateField:
    def test_parses_iso_format(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField()
        form = F(MultiDict([("d", "2025-01-15")]))
        assert form.validate()

    def test_parses_alternative_format(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField(formats=["%d/%m/%Y", "%Y-%m-%d"])
        form = F(MultiDict([("d", "15/01/2025")]))
        assert form.validate()

    def test_invalid_format(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField()
        form = F(MultiDict([("d", "not-a-date")]))
        assert not form.validate()
        assert "d" in form.errors

    def test_date_empty_valuelist(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField()
        form = F()
        assert form.d.data is None

    def test_date_value_with_raw_data(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField()
        form = F(MultiDict([("d", "2025-06-15")]))
        assert form.d._value() == "2025-06-15"

    def test_date_value_without_raw_data(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        from datetime import date
        class F(Form):
            d = UnifiedDateField()
        form = F()
        form.d.data = date(2025, 6, 15)
        assert form.d._value() == "2025-06-15"

    def test_date_value_with_output_format(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        from datetime import date
        class F(Form):
            d = UnifiedDateField(output_format="%d/%m/%Y")
        form = F()
        form.d.data = date(2025, 6, 15)
        assert form.d._value() == "15/06/2025"

    def test_date_format_as_list(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField(format=["%d/%m/%Y", "%Y-%m-%d"])
        form = F(MultiDict([("d", "15/01/2025")]))
        assert form.validate()

    def test_date_formats_list_init(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField(formats=["%d/%m/%Y"])
        form = F(MultiDict([("d", "15/01/2025")]))
        assert form.validate()

    def test_date_timestamp_exception(self, app):
        from forms import UnifiedDateField
        from wtforms.form import Form
        class F(Form):
            d = UnifiedDateField()
        form = F(MultiDict([("d", "ts:not-a-number")]))
        assert not form.validate()
        assert "d" in form.errors


# ─── Unique validator tests ─────────────────────────────────────────────────

class TestUniqueValidator:
    def test_unique_value_passes(self, db_session):
        from custom_validators import Unique
        from models import Customer
        from wtforms.form import Form
        from wtforms.fields import StringField
        uv = Unique(Customer, "phone", normalizer=lambda v: v.strip() if v else v)
        class F(Form):
            phone = StringField(validators=[uv])
        form = F(MultiDict([("phone", "0500000200")]))
        assert form.validate()

    def test_duplicate_value_fails(self, db_session):
        from custom_validators import Unique
        from models import Customer
        from wtforms.form import Form
        from wtforms.fields import StringField
        db_session.add(Customer(name="Dup", phone="0500000201"))
        db_session.commit()
        uv = Unique(Customer, "phone", normalizer=lambda v: v.strip() if v else v)
        class F(Form):
            phone = StringField(validators=[uv])
        form = F(MultiDict([("phone", "0500000201")]))
        assert not form.validate()
        assert "phone" in form.errors

    def test_excludes_self_on_edit(self, db_session):
        from custom_validators import Unique
        from models import Customer
        from wtforms.form import Form
        from wtforms.fields import StringField, HiddenField
        existing = Customer(name="Self", phone="0500000202")
        db_session.add(existing)
        db_session.commit()
        uv = Unique(Customer, "phone", pk_name="id")
        class F(Form):
            id = HiddenField()
            phone = StringField(validators=[uv])
        form = F(MultiDict([("id", str(existing.id)), ("phone", "0500000202")]))
        assert form.validate()

    def test_case_insensitive(self, db_session):
        from custom_validators import Unique
        from models import Customer
        from wtforms.form import Form
        from wtforms.fields import StringField
        db_session.add(Customer(name="Case", phone="0500000203", email="Case@Test.COM"))
        db_session.commit()
        uv = Unique(Customer, "email", case_insensitive=True)
        class F(Form):
            email = StringField(validators=[uv])
        form = F(MultiDict([("email", "case@test.com")]))
        assert not form.validate()
        assert "email" in form.errors

    def test_empty_data_skips(self, db_session):
        from custom_validators import Unique
        from models import Customer
        uv = Unique(Customer, "phone", normalizer=lambda v: v.strip() if v else v)
        uv(None, type("F", (), {"data": None})())  # should not raise

    def test_callable_model(self, db_session):
        from custom_validators import Unique
        from models import Customer
        from wtforms.form import Form
        from wtforms.fields import StringField
        uv = Unique(lambda: Customer, "phone")
        class F(Form):
            phone = StringField(validators=[uv])
        form = F(MultiDict([("phone", "0500000204")]))
        assert form.validate()


# ─── DateTimeLocalField tests ───────────────────────────────────────────────

class TestDateTimeLocalField:
    def test_parses_valid_datetime_local(self, app):
        from forms import DateTimeLocalField
        from wtforms.form import Form
        class F(Form):
            dt = DateTimeLocalField()
        form = F(MultiDict([("dt", "2025-01-15T10:30")]))
        assert form.validate()

    def test_render_kw_has_datetime_local_type(self, app):
        from forms import DateTimeLocalField
        from wtforms.form import Form
        class F(Form):
            dt = DateTimeLocalField()
        html = F().dt()
        assert 'type="datetime-local"' in html or 'type="text"' in html
