from decimal import Decimal
from unittest import mock
from werkzeug.datastructures import MultiDict


def _fd(**kw):
    items = []
    for k, v in kw.items():
        if isinstance(v, list):
            for item in v:
                items.append((k, str(item)))
        else:
            items.append((k, str(v) if v is not None else ""))
    return MultiDict(items)


class TestTransferForm:
    FORM_META = {"csrf": False}

    def _wh(self, db_session, name="WH"):
        from models import Warehouse
        w = Warehouse(name=name, warehouse_type="PHYSICAL")
        db_session.add(w)
        db_session.commit()
        return w

    def _cat(self, db_session, name="Cat"):
        from models import ProductCategory
        c = ProductCategory(name=name)
        db_session.add(c)
        db_session.commit()
        return c

    def _prod(self, db_session, cat, name="Prod"):
        from models import Product
        p = Product(name=name, category_id=cat.id,
                    price=100, purchase_price=50, currency="ILS")
        db_session.add(p)
        db_session.commit()
        return p

    def test_valid_transfer(self, db_session):
        from forms import TransferForm
        wh_src = self._wh(db_session, "Src")
        wh_dst = self._wh(db_session, "Dst")
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        form = TransferForm(
            _fd(product_id=str(prod.id),
                source_id=str(wh_src.id),
                destination_id=str(wh_dst.id),
                quantity="10", direction="IN",
                transfer_date="2025-06-15 10:30"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_same_source_destination(self, db_session):
        from forms import TransferForm
        wh = self._wh(db_session)
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        form = TransferForm(
            _fd(product_id=str(prod.id),
                source_id=str(wh.id),
                destination_id=str(wh.id),
                quantity="10", direction="IN"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "destination_id" in form.errors

    def test_insufficient_stock_for_out(self, db_session):
        from forms import TransferForm
        wh_src = self._wh(db_session, "Src")
        wh_dst = self._wh(db_session, "Dst")
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        form = TransferForm(
            _fd(product_id=str(prod.id),
                source_id=str(wh_src.id),
                destination_id=str(wh_dst.id),
                quantity="9999", direction="OUT"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "quantity" in form.errors

    def test_apply_to(self, db_session):
        from models import Transfer
        from forms import TransferForm
        wh_src = self._wh(db_session, "Src")
        wh_dst = self._wh(db_session, "Dst")
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        form = TransferForm(
            _fd(product_id=str(prod.id),
                source_id=str(wh_src.id),
                destination_id=str(wh_dst.id),
                quantity="5", direction="IN",
                notes="test note"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        t = Transfer()
        form.apply_to(t)
        assert t.product_id == prod.id
        assert t.source_id == wh_src.id
        assert t.destination_id == wh_dst.id
        assert t.quantity == 5
        assert t.direction == "IN"
        assert t.notes == "test note"

    def test_missing_quantity(self, db_session):
        from forms import TransferForm
        wh_src = self._wh(db_session, "Src")
        wh_dst = self._wh(db_session, "Dst")
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        form = TransferForm(
            _fd(product_id=str(prod.id),
                source_id=str(wh_src.id),
                destination_id=str(wh_dst.id),
                quantity="", direction="IN"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "quantity" in form.errors


class TestSettlementRangeForm:
    FORM_META = {"csrf": False}

    def test_valid_empty(self, db_session):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(_fd(), meta=self.FORM_META)
        assert form.validate() is True

    def test_valid_range(self, db_session):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(
            _fd(start="2025-01-01", end="2025-12-31"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_end_before_start(self, db_session):
        from forms import SettlementRangeForm
        form = SettlementRangeForm(
            _fd(start="2025-12-31", end="2025-01-01"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "end" in form.errors


class TestRegistrationForm:
    FORM_META = {"csrf": False}

    def _role(self, db_session):
        from models import Role
        r = Role(name="admin", is_default=True)
        db_session.add(r)
        db_session.commit()
        return r

    def _make_user(self, db_session, username, email):
        from models import User
        u = User(username=username, email=email)
        u.set_password("test123")
        db_session.add(u)
        db_session.commit()
        return u

    def test_valid_registration(self, db_session):
        from forms import RegistrationForm
        r = self._role(db_session)
        form = RegistrationForm(
            _fd(username="newuser", email="new@test.com",
                password="secret123", confirm="secret123",
                role=str(r.id)),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_duplicate_username(self, db_session):
        from forms import RegistrationForm
        r = self._role(db_session)
        self._make_user(db_session, "taken", "taken@test.com")
        form = RegistrationForm(
            _fd(username="taken", email="other@test.com",
                password="secret123", confirm="secret123",
                role=str(r.id)),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "username" in form.errors

    def test_duplicate_email(self, db_session):
        from forms import RegistrationForm
        r = self._role(db_session)
        self._make_user(db_session, "existing", "dup@test.com")
        form = RegistrationForm(
            _fd(username="newuser", email="dup@test.com",
                password="secret123", confirm="secret123",
                role=str(r.id)),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_password_mismatch(self, db_session):
        from forms import RegistrationForm
        r = self._role(db_session)
        form = RegistrationForm(
            _fd(username="newuser", email="new@test.com",
                password="secret123", confirm="different",
                role=str(r.id)),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "confirm" in form.errors


class TestPasswordResetRequestForm:
    FORM_META = {"csrf": False}

    def test_validates_email(self, db_session):
        from forms import PasswordResetRequestForm
        form = PasswordResetRequestForm(
            _fd(email="Test@Example.COM"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.email.data == "test@example.com"


class TestUserForm:
    FORM_META = {"csrf": False}

    @staticmethod
    def _make_role(db_session, name="owner"):
        from models import Role
        r = Role(name=name)
        db_session.add(r)
        db_session.commit()
        return r

    @staticmethod
    def _make_user(db_session, username, email):
        from models import User
        u = User(username=username, email=email)
        u.set_password("test123")
        db_session.add(u)
        db_session.commit()
        return u

    def _make_form(self, app, db_session, formdata, editing_user_id=None):
        from forms import UserForm
        with app.test_request_context():
            admin = mock.MagicMock()
            admin.username = "admin"
            admin.role.name = "admin"
            admin.is_system_account = True
            with mock.patch("flask_login.utils._get_user", return_value=admin):
                if editing_user_id:
                    with mock.patch("flask.request.view_args", {"user_id": editing_user_id}):
                        return UserForm(formdata, meta=self.FORM_META)
                return UserForm(formdata, meta=self.FORM_META)

    def test_valid_user_form(self, app, db_session):
        r = self._make_role(db_session)
        form = self._make_form(
            app, db_session,
            _fd(username="staff1", email="staff1@test.com",
                role_id=str(r.id), is_active="y"),
        )
        assert form.validate() is True

    def test_duplicate_username(self, app, db_session):
        r = self._make_role(db_session)
        self._make_user(db_session, "taken", "taken@test.com")
        form = self._make_form(
            app, db_session,
            _fd(username="taken", email="other@test.com",
                role_id=str(r.id), is_active="y"),
        )
        assert form.validate() is False
        assert "username" in form.errors

    def test_duplicate_email(self, app, db_session):
        r = self._make_role(db_session)
        self._make_user(db_session, "existing", "dup@test.com")
        form = self._make_form(
            app, db_session,
            _fd(username="newstaff", email="dup@test.com",
                role_id=str(r.id), is_active="y"),
        )
        assert form.validate() is False
        assert "email" in form.errors

    def test_apply_to(self, app, db_session):
        from models import User
        r = self._make_role(db_session)
        form = self._make_form(
            app, db_session,
            _fd(username="applied", email="applied@test.com",
                role_id=str(r.id), is_active="y"),
        )
        assert form.validate() is True
        u = User()
        form.apply_to(u)
        assert u.username == "applied"
        assert u.email == "applied@test.com"
        assert u.role_id == r.id
        assert u.is_active is True

    def test_apply_to_sets_password(self, app, db_session):
        from models import User
        r = self._make_role(db_session)
        form = self._make_form(
            app, db_session,
            _fd(username="withpw", email="withpw@test.com",
                role_id=str(r.id), is_active="y",
                password="secret123", confirm="secret123"),
        )
        assert form.validate() is True
        u = User()
        form.apply_to(u)
        assert u.check_password("secret123") is True


class TestRoleForm:
    FORM_META = {"csrf": False}

    def test_valid_role(self, db_session):
        from forms import RoleForm
        form = RoleForm(
            _fd(name="editor", description="Can edit"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_duplicate_name(self, db_session):
        from models import Role
        from forms import RoleForm
        db_session.add(Role(name="duperole"))
        db_session.commit()
        form = RoleForm(
            _fd(name="duperole"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_self_name_allowed_on_edit(self, db_session):
        from models import Role
        from forms import RoleForm
        r = Role(name="editrole")
        db_session.add(r)
        db_session.commit()
        form = RoleForm(
            _fd(id=str(r.id), name="editrole"),
            meta=self.FORM_META,
        )
        assert form.validate() is True


class TestPermissionForm:
    FORM_META = {"csrf": False}

    def test_valid_permission(self, db_session):
        from forms import PermissionForm
        form = PermissionForm(
            _fd(name="Manage Users"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.name.data == "Manage Users"

    def test_code_normalization(self, db_session):
        from forms import PermissionForm
        form = PermissionForm(
            _fd(name="Test", code="  Manage-Users  "),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        assert form.code.data == "manage_users"


class TestProductSupplierLoanForm:
    FORM_META = {"csrf": False}

    def _cat(self, db_session):
        from models import ProductCategory
        c = ProductCategory(name="Cat")
        db_session.add(c)
        db_session.commit()
        return c

    def _prod(self, db_session, cat):
        from models import Product
        p = Product(name="LoanProd", category_id=cat.id,
                    price=100, purchase_price=50, currency="ILS")
        db_session.add(p)
        db_session.commit()
        return p

    def _supplier(self, db_session):
        from models import Supplier
        s = Supplier(name="LoanSupplier")
        db_session.add(s)
        db_session.commit()
        return s

    def test_valid_loan(self, db_session):
        from forms import ProductSupplierLoanForm
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        sup = self._supplier(db_session)
        form = ProductSupplierLoanForm(
            _fd(product_id=str(prod.id),
                supplier_id=str(sup.id)),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_settled_requires_deferred_price(self, db_session):
        from forms import ProductSupplierLoanForm
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        sup = self._supplier(db_session)
        form = ProductSupplierLoanForm(
            _fd(product_id=str(prod.id),
                supplier_id=str(sup.id),
                is_settled="y", deferred_price="0"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "deferred_price" in form.errors

    def test_settled_with_deferred_price(self, db_session):
        from forms import ProductSupplierLoanForm
        cat = self._cat(db_session)
        prod = self._prod(db_session, cat)
        sup = self._supplier(db_session)
        form = ProductSupplierLoanForm(
            _fd(product_id=str(prod.id),
                supplier_id=str(sup.id),
                is_settled="y", deferred_price="500"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
