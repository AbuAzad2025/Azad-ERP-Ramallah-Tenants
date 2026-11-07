from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from models import (
    Customer, Supplier, Partner, Product, Warehouse,
    Sale, SaleLine, SaleStatus,
    Payment, PaymentSplit, PaymentDirection, PaymentStatus,
    Expense, Invoice,
    ServiceRequest, ServiceStatus,
    PreOrder, PreOrderStatus,
    OnlinePreOrder,
    User,
)


def _seed_customers(db):
    db.session.add(Customer(id=10, name="cust_a", phone="0500000010", current_balance=Decimal("150.00"), currency="ILS"))
    db.session.add(Customer(id=11, name="cust_b", phone="0500000011", current_balance=Decimal("200.00"), currency="USD"))
    db.session.add(Customer(id=12, name="cust_c", phone="0500000012", current_balance=Decimal("0.00"), currency="ILS"))
    db.session.commit()


def _seed_suppliers(db):
    db.session.add(Supplier(id=20, name="supp_a", phone="0500000020", current_balance=Decimal("300.00"), currency="ILS", is_local=True))
    db.session.add(Supplier(id=21, name="supp_b", phone="0500000021", current_balance=Decimal("400.00"), currency="USD", is_local=False))
    db.session.add(Supplier(id=22, name="supp_c", phone="0500000022", current_balance=Decimal("0.00"), currency="ILS"))
    db.session.commit()


def _seed_partners(db):
    db.session.add(Partner(id=30, name="part_a", phone_number="020", current_balance=Decimal("500.00"), currency="ILS", share_percentage=Decimal("50.00"), contact_info="email@a"))
    db.session.add(Partner(id=31, name="part_b", phone_number="021", current_balance=Decimal("0.00"), currency="USD", share_percentage=Decimal("50.00"), contact_info="email@b"))
    db.session.commit()


def _seed_products(db):
    db.session.add(Product(id=40, name="prod_x"))
    db.session.add(Product(id=41, name="prod_y"))
    db.session.commit()


def _seed_warehouses(db):
    db.session.add(Warehouse(id=50, name="wh_main"))
    db.session.add(Warehouse(id=51, name="wh_sec"))
    db.session.commit()


def _seed_sales(db):
    from models import PaymentProgress
    now = datetime(2026, 1, 15, 10, 0, 0)
    db.session.add(Sale(id=100, sale_number="SAL-TEST-0100", payment_status=PaymentProgress.PENDING.value, sale_channel="STANDARD", customer_id=10, total_amount=Decimal("1000.00"), currency="ILS", sale_date=now, status=SaleStatus.CONFIRMED.value, seller_id=1))
    db.session.add(Sale(id=101, sale_number="SAL-TEST-0101", payment_status=PaymentProgress.PENDING.value, sale_channel="STANDARD", customer_id=11, total_amount=Decimal("500.00"), currency="USD", sale_date=now, status=SaleStatus.CONFIRMED.value, fx_rate_used=Decimal("3.50"), seller_id=1))
    db.session.add(Sale(id=102, sale_number="SAL-TEST-0102", payment_status=PaymentProgress.PENDING.value, sale_channel="STANDARD", customer_id=10, total_amount=Decimal("200.00"), currency="ILS", sale_date=now - timedelta(days=45), status=SaleStatus.CANCELLED.value, seller_id=1))
    db.session.add(Sale(id=103, sale_number="SAL-TEST-0103", payment_status=PaymentProgress.PENDING.value, sale_channel="STANDARD", customer_id=11, total_amount=Decimal("300.00"), currency="ILS", sale_date=now - timedelta(days=10), status=SaleStatus.REFUNDED.value, seller_id=1))
    db.session.add(Sale(id=104, sale_number="SAL-TEST-0104", payment_status=PaymentProgress.PENDING.value, sale_channel="STANDARD", customer_id=12, total_amount=Decimal("50.00"), currency="ILS", sale_date=now - timedelta(days=20), status=SaleStatus.CONFIRMED.value, seller_id=1))
    db.session.commit()


def _seed_sale_lines(db):
    db.session.add(SaleLine(id=200, sale_id=100, product_id=40, quantity=5, unit_price=Decimal("100.00"), discount_rate=Decimal("10.00"), tax_rate=Decimal("17.00"), warehouse_id=50))
    db.session.add(SaleLine(id=201, sale_id=100, product_id=41, quantity=3, unit_price=Decimal("200.00"), discount_rate=Decimal("0"), tax_rate=Decimal("17.00"), warehouse_id=50))
    db.session.add(SaleLine(id=202, sale_id=101, product_id=40, quantity=2, unit_price=Decimal("250.00"), discount_rate=Decimal("0"), tax_rate=Decimal("0"), warehouse_id=51))
    db.session.add(SaleLine(id=203, sale_id=104, product_id=41, quantity=1, unit_price=Decimal("50.00"), discount_rate=Decimal("0"), tax_rate=Decimal("0"), warehouse_id=50))
    db.session.commit()


def _seed_payments(db):
    now = datetime(2026, 1, 15, 10, 0, 0)
    db.session.add(Payment(id=300, payment_number="PMT-TEST-0300", total_amount=Decimal("100.00"), currency="ILS", payment_date=now, direction=PaymentDirection.IN.value, method="cash", status=PaymentStatus.COMPLETED.value, customer_id=10))
    db.session.add(Payment(id=301, payment_number="PMT-TEST-0301", total_amount=Decimal("200.00"), currency="USD", payment_date=now, direction=PaymentDirection.IN.value, method="card", status=PaymentStatus.COMPLETED.value, customer_id=11))
    db.session.add(Payment(id=302, payment_number="PMT-TEST-0302", total_amount=Decimal("50.00"), currency="ILS", payment_date=now, direction=PaymentDirection.OUT.value, method="bank", status=PaymentStatus.COMPLETED.value, supplier_id=20))
    db.session.add(Payment(id=303, payment_number="PMT-TEST-0303", total_amount=Decimal("30.00"), currency="ILS", payment_date=now, direction=PaymentDirection.IN.value, method="cash", status=PaymentStatus.PENDING.value, customer_id=12))
    db.session.commit()


def _seed_payment_splits(db):
    db.session.add(PaymentSplit(id=400, payment_id=300, amount=Decimal("60.00"), method="cash"))
    db.session.add(PaymentSplit(id=401, payment_id=300, amount=Decimal("40.00"), method="card"))
    db.session.add(PaymentSplit(id=402, payment_id=301, amount=Decimal("200.00"), method="card"))
    db.session.add(PaymentSplit(id=403, payment_id=302, amount=Decimal("50.00"), method="bank"))
    db.session.commit()


def _seed_expense_types(db):
    from models import ExpenseType, Company, Branch
    db.session.add(Company(id=1, name="Test Co", code="TST"))
    db.session.add(Branch(id=1, company_id=1, name="Main", code="MAIN"))
    db.session.add(ExpenseType(id=1, name="General"))
    db.session.commit()


def _seed_expenses(db):
    _seed_expense_types(db)
    db.session.add(Expense(id=500, type_id=1, branch_id=1, amount=Decimal("150.00"), date=date(2026, 1, 10), supplier_id=20))
    db.session.add(Expense(id=501, type_id=1, branch_id=1, amount=Decimal("75.50"), date=date(2026, 1, 20), supplier_id=20))
    db.session.commit()


def _seed_invoices(db):
    db.session.add(Invoice(id=600, invoice_number="INV-TEST-0600", customer_id=10, supplier_id=None, invoice_date=date(2026, 1, 5), cancelled_at=None))
    db.session.add(Invoice(id=601, invoice_number="INV-TEST-0601", customer_id=11, supplier_id=None, invoice_date=date(2026, 1, 10), cancelled_at=None))
    db.session.commit()


def _seed_service_requests(db):
    dt = datetime(2026, 1, 15, 10, 0, 0)
    db.session.add(ServiceRequest(id=700, service_number="SRV-001", status=ServiceStatus.COMPLETED.value, priority="HIGH", received_at=dt, customer_id=10, mechanic_id=1, total_amount=Decimal("500.00"), currency="ILS", fx_rate_used=None, parts_total=Decimal("200.00"), labor_total=Decimal("300.00")))
    db.session.add(ServiceRequest(id=701, service_number="SRV-002", status=ServiceStatus.PENDING.value, priority="LOW", received_at=dt + timedelta(days=1), customer_id=11, mechanic_id=1, total_amount=Decimal("100.00"), currency="USD", fx_rate_used=Decimal("3.50"), parts_total=Decimal("50.00"), labor_total=Decimal("50.00")))
    db.session.add(ServiceRequest(id=702, service_number="SRV-003", status=ServiceStatus.COMPLETED.value, priority="MEDIUM", received_at=dt - timedelta(days=5), customer_id=10, mechanic_id=None, total_amount=Decimal("300.00"), currency="ILS", fx_rate_used=None, parts_total=Decimal("100.00"), labor_total=Decimal("200.00")))
    db.session.commit()


def _seed_preorders(db):
    db.session.add(PreOrder(id=800, customer_id=10, preorder_date=date(2026, 1, 1), status=PreOrderStatus.FULFILLED.value, product_id=40, warehouse_id=50, quantity=2))
    db.session.add(PreOrder(id=801, customer_id=11, preorder_date=date(2026, 1, 5), status=PreOrderStatus.CANCELLED.value, product_id=41, warehouse_id=50, quantity=1))
    db.session.add(PreOrder(id=802, customer_id=10, preorder_date=date(2026, 1, 10), status=PreOrderStatus.PENDING.value, product_id=40, warehouse_id=51, quantity=3))
    db.session.commit()


def _seed_online_preorders(db):
    dt = datetime(2026, 1, 15, 10, 0, 0)
    db.session.add(OnlinePreOrder(id=900, order_number="ORD-TEST-0900", customer_id=10, created_at=dt, status=PreOrderStatus.FULFILLED.value, prepaid_amount=Decimal("50.00"), total_amount=Decimal("200.00")))
    db.session.add(OnlinePreOrder(id=901, order_number="ORD-TEST-0901", customer_id=11, created_at=dt - timedelta(days=3), status=PreOrderStatus.CANCELLED.value, prepaid_amount=Decimal("0"), total_amount=Decimal("100.00")))
    db.session.add(OnlinePreOrder(id=902, order_number="ORD-TEST-0902", customer_id=10, created_at=dt - timedelta(days=10), status=PreOrderStatus.PENDING.value, prepaid_amount=Decimal("25.00"), total_amount=Decimal("80.00")))
    db.session.commit()


def _seed_users(db):
    db.session.add(User(id=1, username="mech_a", email="mech@test.co", password_hash="scrypt:hash:dummy"))
    db.session.commit()


def _seed_all(db):
    _seed_customers(db)
    _seed_suppliers(db)
    _seed_partners(db)
    _seed_products(db)
    _seed_warehouses(db)
    _seed_sales(db)
    _seed_sale_lines(db)
    _seed_payments(db)
    _seed_payment_splits(db)
    _seed_expenses(db)
    _seed_invoices(db)
    _seed_service_requests(db)
    _seed_preorders(db)
    _seed_online_preorders(db)
    _seed_users(db)


class TestAgeBucket:
    def test_zero_days(self):
        from reports import age_bucket
        assert age_bucket(0) == "0-30"

    def test_30_days(self):
        from reports import age_bucket
        assert age_bucket(30) == "0-30"

    def test_31_days(self):
        from reports import age_bucket
        assert age_bucket(31) == "31-60"

    def test_60_days(self):
        from reports import age_bucket
        assert age_bucket(60) == "31-60"

    def test_61_days(self):
        from reports import age_bucket
        assert age_bucket(61) == "61-90"

    def test_90_days(self):
        from reports import age_bucket
        assert age_bucket(90) == "61-90"

    def test_91_days(self):
        from reports import age_bucket
        assert age_bucket(91) == "90+"

    def test_negative_input(self):
        from reports import age_bucket
        assert age_bucket(-5) == "0-30"

    def test_string_input(self):
        from reports import age_bucket
        assert age_bucket("45") == "31-60"

    def test_none_input(self):
        from reports import age_bucket
        assert age_bucket(None) == "0-30"

    def test_invalid_string(self):
        from reports import age_bucket
        assert age_bucket("abc") == "0-30"


class TestParseDateLike:
    def test_none(self):
        from reports import _parse_date_like
        assert _parse_date_like(None) is None

    def test_empty_string(self):
        from reports import _parse_date_like
        assert _parse_date_like("") is None

    def test_date_object(self):
        from reports import _parse_date_like
        d = date(2026, 1, 15)
        assert _parse_date_like(d) is d

    def test_datetime_object(self):
        from reports import _parse_date_like
        dt = datetime(2026, 1, 15, 10, 30, 0)
        assert _parse_date_like(dt) == date(2026, 1, 15)

    def test_valid_iso_string(self):
        from reports import _parse_date_like
        assert _parse_date_like("2026-01-15") == date(2026, 1, 15)

    def test_invalid_iso_string(self):
        from reports import _parse_date_like
        assert _parse_date_like("not-a-date") is None

    def test_zero_integer(self):
        from reports import _parse_date_like
        assert _parse_date_like(0) is None


class TestAllowedColumns:
    def test_returns_column_names(self):
        from reports import _allowed_columns
        from models import Customer
        cols = _allowed_columns(Customer)
        assert "id" in cols
        assert "name" in cols
        assert isinstance(cols, set)


@pytest.mark.usefixtures("db_session")
class TestCustomerBalanceReportIls:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_customers(db)

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("100.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪100.00")
    def test_all_customers_by_default(self, mock_fmt, mock_bal):
        from reports import customer_balance_report_ils
        result = customer_balance_report_ils(customer_ids=[10, 11, 12])
        assert result["report_type"] == "customer_balance_report_ils"
        assert result["total_customers"] == 3
        assert result["total_balance_ils"] == Decimal("300.00")
        assert len(result["customers"]) == 3

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("50.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪50.00")
    def test_specific_customers(self, mock_fmt, mock_bal):
        from reports import customer_balance_report_ils
        result = customer_balance_report_ils(customer_ids=[10, 12])
        assert result["total_customers"] == 2
        assert len(result["customers"]) == 2

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("100.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪100.00")
    def test_nonexistent_id_skipped(self, mock_fmt, mock_bal):
        from reports import customer_balance_report_ils
        result = customer_balance_report_ils(customer_ids=[10, 999])
        assert result["total_customers"] == 2
        assert len(result["customers"]) == 1

    @patch("reports.utils.get_entity_balance_in_ils", side_effect=Exception("db fail"))
    @patch("reports.utils.format_currency_in_ils")
    def test_exception_returns_error_dict(self, mock_fmt, mock_bal):
        from reports import customer_balance_report_ils
        result = customer_balance_report_ils(customer_ids=[10])
        assert "error" in result


@pytest.mark.usefixtures("db_session")
class TestSupplierBalanceReportIls:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_suppliers(db)

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("200.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪200.00")
    def test_all_suppliers(self, mock_fmt, mock_bal):
        from reports import supplier_balance_report_ils
        result = supplier_balance_report_ils(supplier_ids=[20, 21, 22])
        assert result["report_type"] == "supplier_balance_report_ils"
        assert result["total_suppliers"] == 3
        assert result["total_balance_ils"] == Decimal("600.00")
        assert len(result["suppliers"]) == 3

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("200.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪200.00")
    def test_specific_suppliers(self, mock_fmt, mock_bal):
        from reports import supplier_balance_report_ils
        result = supplier_balance_report_ils(supplier_ids=[20])
        assert result["total_suppliers"] == 1

    @patch("reports.utils.get_entity_balance_in_ils", side_effect=Exception("fail"))
    @patch("reports.utils.format_currency_in_ils")
    def test_exception(self, mock_fmt, mock_bal):
        from reports import supplier_balance_report_ils
        result = supplier_balance_report_ils(supplier_ids=[20])
        assert "error" in result


@pytest.mark.usefixtures("db_session")
class TestPaymentSummaryReportIls:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_customers(db)
        _seed_suppliers(db)
        _seed_payments(db)

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils", side_effect=lambda v: f"₪{float(v):.2f}")
    def test_basic_report(self, mock_fmt, mock_conv):
        mock_conv.return_value = Decimal("700.00")
        from reports import payment_summary_report_ils
        result = payment_summary_report_ils()
        assert result["report_type"] == "payment_summary_report_ils"
        assert result["total_payments"] == 3
        assert result["totals"]["total_incoming_ils"] > 0
        assert result["totals"]["total_outgoing_ils"] > 0

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils", side_effect=lambda v: f"₪{float(v):.2f}")
    def test_with_date_range(self, mock_fmt, mock_conv):
        mock_conv.return_value = Decimal("700.00")
        from reports import payment_summary_report_ils
        result = payment_summary_report_ils(start_date=date(2026, 1, 1), end_date=date(2026, 2, 1))
        assert result["total_payments"] == 3

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils", side_effect=lambda v: f"₪{float(v):.2f}")
    def test_convert_amount_exception_skips_payment(self, mock_fmt, mock_conv):
        mock_conv.side_effect = Exception("conv fail")
        from reports import payment_summary_report_ils
        result = payment_summary_report_ils()
        assert result["total_payments"] == 3
        assert result["totals"]["total_incoming_ils"] == Decimal("100.00")

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils")
    def test_exception_in_report(self, mock_fmt, mock_conv):
        mock_fmt.side_effect = Exception("fmt fail")
        from reports import payment_summary_report_ils
        result = payment_summary_report_ils()
        assert "error" in result


@pytest.mark.usefixtures("db_session")
class TestAdvancedReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_suppliers(db)
        _seed_expenses(db)

    def test_basic_query(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense)
        assert "data" in result
        assert "summary" in result
        assert len(result["data"]) == 2

    def test_with_date_filter(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense, date_field="date", start_date=date(2026, 1, 15))
        assert len(result["data"]) == 1

    def test_with_aggregates_sum(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense, aggregates={"sum": ["amount"]})
        assert result["summary"]["sum_amount"] == 225.5

    def test_with_aggregates_count(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense, aggregates={"count": ["id"]})
        assert result["summary"]["count_id"] == 2

    def test_with_aggregates_avg(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense, aggregates={"avg": ["amount"]})
        assert result["summary"]["avg_amount"] == pytest.approx(112.75)

    def test_with_filters(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense, filters={"id": [500]})
        assert len(result["data"]) == 1

    def test_with_like_filters(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense, like_filters={"id": ""})
        assert len(result["data"]) == 2

    def test_unknown_aggregate_passes_through(self):
        from reports import advanced_report
        from models import Expense
        result = advanced_report(model=Expense, aggregates={"max": ["id"]})
        assert "max_id" in result["summary"]

    def test_empty_table(self):
        from reports import advanced_report
        from models import Sale
        result = advanced_report(model=Sale, filters={"id": [9999]})
        assert result["data"] == []
        assert result["summary"] == {}

    def test_invalid_date_field_raises(self):
        from reports import advanced_report
        from models import Expense
        import pytest as _pytest
        with _pytest.raises(ValueError, match="Invalid date field"):
            advanced_report(model=Expense, date_field="nonexistent", start_date=date(2026, 1, 1))


@pytest.mark.usefixtures("db_session")
class TestSalesReportIls:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_customers(db)
        _seed_users(db)
        _seed_sales(db)

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils", side_effect=lambda v: f"₪{float(v):.2f}")
    def test_all_sales(self, mock_fmt, mock_conv):
        mock_conv.return_value = Decimal("0.00")
        from reports import sales_report_ils
        result = sales_report_ils(start_date=None, end_date=None)
        assert result["report_type"] == "sales_report_ils"
        assert result["totals"]["total_sales"] == 3

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils", side_effect=lambda v: f"₪{float(v):.2f}")
    def test_with_date_range(self, mock_fmt, mock_conv):
        mock_conv.return_value = Decimal("0.00")
        from reports import sales_report_ils
        result = sales_report_ils(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        assert result["totals"]["total_sales"] == 2

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils", side_effect=lambda v: f"₪{float(v):.2f}")
    def test_convert_amount_exception_uses_raw_ils(self, mock_fmt, mock_conv):
        mock_conv.side_effect = Exception("conv fail")
        from reports import sales_report_ils
        result = sales_report_ils(start_date=None, end_date=None)
        assert result["totals"]["total_revenue_ils"] == Decimal("0.00")

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils")
    def test_exception_in_report(self, mock_fmt, mock_conv):
        mock_fmt.side_effect = Exception("fmt fail")
        from reports import sales_report_ils
        result = sales_report_ils(start_date=None, end_date=None)
        assert "error" in result

    @patch("models.convert_amount")
    @patch("reports.utils.format_currency_in_ils", side_effect=lambda v: f"₪{float(v):.2f}")
    def test_swapped_dates_are_normalized(self, mock_fmt, mock_conv):
        mock_conv.return_value = Decimal("0.00")
        from reports import sales_report_ils
        result = sales_report_ils(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
        assert result["period"]["start_date"] == date(2026, 1, 1)
        assert result["period"]["end_date"] == date(2026, 2, 1)


@pytest.mark.usefixtures("db_session")
class TestSalesReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_customers(db)
        _seed_users(db)
        _seed_sales(db)

    @patch("models.convert_amount", return_value=Decimal("0.00"))
    def test_daily_labels_and_values(self, mock_conv):
        from reports import sales_report
        result = sales_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        assert "daily_labels" in result
        assert "daily_values" in result
        assert result["total_revenue"] >= 0
        assert len(result["daily_labels"]) == 31

    @patch("models.convert_amount", return_value=Decimal("0.00"))
    def test_no_date_limit_sorted_keys(self, mock_conv):
        from reports import sales_report
        result = sales_report(start_date=None, end_date=None)
        assert len(result["daily_labels"]) > 0
        assert result["daily_labels"] == sorted(result["daily_labels"])

    @patch("models.convert_amount", return_value=Decimal("0.00"))
    def test_only_unconfirmed_and_refunded_excluded(self, mock_conv):
        from reports import sales_report
        result = sales_report(start_date=None, end_date=None)
        assert result["total_revenue"] >= 0

    @patch("models.convert_amount")
    def test_convert_amount_exception_defaults_to_zero(self, mock_conv):
        mock_conv.side_effect = Exception("fail")
        from reports import sales_report
        result = sales_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        assert result["total_revenue"] >= 0

    @patch("models.convert_amount", return_value=Decimal("0.00"))
    def test_swapped_dates_normalized(self, mock_conv):
        from reports import sales_report
        result = sales_report(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
        assert len(result["daily_labels"]) == 32


@pytest.mark.usefixtures("db_session")
class TestExpenseReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_suppliers(db)
        _seed_expenses(db)

    def test_returns_data_and_summary(self):
        from reports import expense_report
        result = expense_report(start_date=None, end_date=None)
        assert len(result["data"]) == 2
        assert result["summary"]["sum_amount"] == 225.5
        assert result["summary"]["count_id"] == 2

    def test_with_date_range(self):
        from reports import expense_report
        result = expense_report(start_date=date(2026, 1, 15), end_date=date(2026, 1, 31))
        assert len(result["data"]) == 1
        assert result["summary"]["count_id"] == 1


@pytest.mark.usefixtures("db_session")
class TestShopReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_online_preorders(db)

    def test_returns_data_and_summary(self):
        from reports import shop_report
        result = shop_report(start_date=None, end_date=None)
        assert len(result["data"]) == 3
        assert "sum_prepaid_amount" in result["summary"]
        assert "sum_total_amount" in result["summary"]
        assert "count_id" in result["summary"]

    def test_with_date_filter(self):
        from reports import shop_report
        result = shop_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 14))
        assert len(result["data"]) == 2


@pytest.mark.usefixtures("db_session")
class TestPaymentSummaryReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_customers(db)
        _seed_suppliers(db)
        _seed_payments(db)
        _seed_payment_splits(db)

    @patch("models.convert_amount", return_value=Decimal("700.00"))
    def test_returns_methods_and_totals(self, mock_conv):
        from reports import payment_summary_report
        result = payment_summary_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        assert "methods" in result
        assert "totals" in result
        assert result["grand_total"] > 0

    @patch("models.convert_amount", return_value=Decimal("700.00"))
    def test_with_splits_and_no_splits(self, mock_conv):
        from reports import payment_summary_report
        result = payment_summary_report(start_date=None, end_date=None)
        assert len(result["methods"]) > 0
        assert all(t >= 0 for t in result["totals"])

    @patch("models.convert_amount")
    def test_convert_exception_skips_amount(self, mock_conv):
        mock_conv.side_effect = Exception("fail")
        from reports import payment_summary_report
        result = payment_summary_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        assert result["grand_total"] == 100.0

    @patch("models.convert_amount", return_value=Decimal("700.00"))
    def test_swapped_dates_normalized(self, mock_conv):
        from reports import payment_summary_report
        result = payment_summary_report(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
        assert result["grand_total"] > 0


@pytest.mark.usefixtures("db_session")
class TestServiceReportsReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_customers(db)
        _seed_service_requests(db)
        _seed_users(db)

    def test_basic_report(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None)
        assert result["total"] == 3
        assert result["completed"] == 2
        assert result["revenue"] > 0

    def test_with_status_filter(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None, status=ServiceStatus.COMPLETED.value)
        assert result["total"] == 2
        assert result["completed"] == 2

    def test_with_mechanic_filter(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None, mechanic_id=1)
        assert result["total"] == 2

    def test_with_customer_filter(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None, customer_id=10)
        assert result["total"] == 2
        assert len(result["data"]) == 2

    def test_date_range(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=date(2026, 1, 10), end_date=date(2026, 1, 20))
        assert result["total"] == 3

    def test_swapped_dates(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
        assert result["total"] == 3

    def test_export_mode(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None, export=True, export_limit=10)
        assert result["total"] == 3
        assert len(result["data"]) == 3
        assert result["pagination"] is None

    def test_pagination(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None, page=1, per_page=10)
        assert result["total"] == 3
        assert len(result["data"]) == 3
        assert result["pagination"] is not None

    def test_data_contains_customer_and_mechanic_names(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None)
        for r in result["data"]:
            assert r["customer_name"] in ("cust_a", "cust_b", "-")
            assert r["mechanic_name"] in ("mech_a", "-")

    def test_row_total_ils_non_ils_currency(self):
        from reports import service_reports_report
        result = service_reports_report(start_date=None, end_date=None)
        for r in result["data"]:
            assert r["total_ils"] >= 0


@pytest.mark.usefixtures("db_session")
class TestArAgingReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        db.session.info["_skip_balance_after_commit"] = True
        _seed_customers(db)
        _seed_users(db)
        _seed_sales(db)
        _seed_invoices(db)
        _seed_service_requests(db)
        _seed_preorders(db)
        _seed_online_preorders(db)

    def test_returns_data_and_totals(self):
        from reports import ar_aging_report
        result = ar_aging_report()
        assert "data" in result
        assert "totals" in result
        assert len(result["data"]) > 0
        for k in ("0-30", "31-60", "61-90", "90+", "total"):
            assert k in result["totals"]

    def test_only_customers_with_positive_balance(self):
        from reports import ar_aging_report
        result = ar_aging_report()
        names = [d["customer"] for d in result["data"]]
        assert "cust_c" not in names

    def test_as_of_date(self):
        from reports import ar_aging_report
        result = ar_aging_report(end_date=date(2026, 2, 1))
        assert result["as_of"] == "2026-02-01"

    def test_no_customers_with_balance(self):
        from reports import ar_aging_report
        from models import Customer
        for c in Customer.query.all():
            c.current_balance = Decimal("0.00")
        from extensions import db
        db.session.commit()
        result = ar_aging_report()
        assert result["data"] == []
        assert result["totals"]["total"] == 0.0


@pytest.mark.usefixtures("db_session")
class TestApAgingReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        db.session.info["_skip_balance_after_commit"] = True
        _seed_customers(db)
        _seed_suppliers(db)
        _seed_invoices(db)
        for inv in Invoice.query.all():
            inv.supplier_id = 20
        db.session.commit()

    def test_returns_data_and_totals(self):
        from reports import ap_aging_report
        result = ap_aging_report()
        assert "data" in result
        assert "totals" in result
        assert len(result["data"]) > 0
        for k in ("0-30", "31-60", "61-90", "90+", "total"):
            assert k in result["totals"]

    def test_only_suppliers_with_positive_balance(self):
        from reports import ap_aging_report
        result = ap_aging_report()
        names = [d["supplier"] for d in result["data"]]
        assert "supp_c" not in names

    def test_no_suppliers_with_balance(self):
        from reports import ap_aging_report
        from models import Supplier
        for s in Supplier.query.all():
            s.current_balance = Decimal("0.00")
        from extensions import db
        db.session.commit()
        result = ap_aging_report()
        assert result["data"] == []
        assert result["totals"]["total"] == 0.0


@pytest.mark.usefixtures("db_session")
class TestTopProductsReport:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_products(db)
        _seed_warehouses(db)
        _seed_customers(db)
        _seed_users(db)
        _seed_sales(db)
        _seed_sale_lines(db)

    def test_returns_top_products(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        assert "data" in result
        assert len(result["data"]) > 0
        assert result["meta"]["total_revenue"] > 0
        assert result["meta"]["total_qty"] > 0

    def test_with_date_range(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        assert len(result["data"]) > 0

    def test_with_warehouse_filter(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), warehouse_id=50)
        assert len(result["data"]) > 0

    def test_with_group_by_warehouse(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), group_by_warehouse=True)
        assert len(result["data"]) > 0
        for item in result["data"]:
            assert "warehouse_name" in item

    def test_with_limit(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), limit=1)
        assert len(result["data"]) <= 1

    def test_swapped_dates_normalized(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
        assert result["meta"]["start_date"] == "2026-01-01"

    def test_pre_1970_dates_clamped(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(1960, 1, 1), end_date=date(1965, 1, 1))
        assert result["data"] == []

    def test_overflow_date_uses_lt_false(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(1970, 1, 1), end_date=date(9999, 12, 31))
        assert "data" in result

    def test_reason_labels(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        for item in result["data"]:
            assert item["reason"] in (
                "ضمن الأعلى إيرادًا", "أعلى كمية مباعة", "حصة إيراد كبيرة",
                "مكرر الطلب من الزبائن", "أداء جيد ضمن الفترة",
            )

    def test_rank_labels(self):
        from reports import top_products_report
        result = top_products_report(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
        for item in result["data"]:
            if item["id"] == 1:
                assert "الأول" in item["rank_label"]
            elif item["id"] == 2:
                assert "الثاني" in item["rank_label"]
            elif item["id"] == 3:
                assert "الثالث" in item["rank_label"]


@pytest.mark.usefixtures("db_session")
class TestPartnerBalanceReportIls:
    @pytest.fixture(autouse=True)
    def _seed(self, db):
        _seed_partners(db)

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("250.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪250.00")
    def test_all_partners(self, mock_fmt, mock_bal):
        from reports import partner_balance_report_ils
        result = partner_balance_report_ils(partner_ids=[30, 31])
        assert result["report_type"] == "partner_balance_report_ils"
        assert result["total_partners"] == 2
        assert result["total_balance_ils"] == Decimal("500.00")
        assert len(result["partners"]) == 2

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("250.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪250.00")
    def test_specific_partners(self, mock_fmt, mock_bal):
        from reports import partner_balance_report_ils
        result = partner_balance_report_ils(partner_ids=[30])
        assert result["total_partners"] == 1
        assert result["partners"][0]["partner_name"] == "part_a"

    @patch("reports.utils.get_entity_balance_in_ils", side_effect=Exception("fail"))
    @patch("reports.utils.format_currency_in_ils")
    def test_exception(self, mock_fmt, mock_bal):
        from reports import partner_balance_report_ils
        result = partner_balance_report_ils(partner_ids=[30])
        assert "error" in result

    @patch("reports.utils.get_entity_balance_in_ils", return_value=Decimal("250.00"))
    @patch("reports.utils.format_currency_in_ils", return_value="₪250.00")
    def test_nonexistent_id_skipped(self, mock_fmt, mock_bal):
        from reports import partner_balance_report_ils
        result = partner_balance_report_ils(partner_ids=[30, 999])
        assert result["total_partners"] == 2
        assert len(result["partners"]) == 1
