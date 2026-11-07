from decimal import Decimal
from werkzeug.datastructures import MultiDict


def _fd(**kw):
    return MultiDict(list(kw.items()))


class TestProductCategoryForm:
    FORM_META = {"csrf": False}

    def test_valid_form(self, db_session):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(
            _fd(name="Test Category", is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_missing_name(self, db_session):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(
            _fd(name="", is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_name_too_long(self, db_session):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(
            _fd(name="x" * 101, is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_duplicate_name(self, db_session):
        from models import ProductCategory
        from forms import ProductCategoryForm
        db_session.add(ProductCategory(name="UniqueCat"))
        db_session.commit()
        form = ProductCategoryForm(
            _fd(name="UniqueCat", is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_self_parent_prevents_circular(self, db_session):
        from models import ProductCategory
        from forms import ProductCategoryForm
        cat = ProductCategory(name="Parent")
        db_session.add(cat)
        db_session.commit()
        form = ProductCategoryForm(
            _fd(id=str(cat.id), name="Child",
                parent_id=str(cat.id), is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_cyclic_parent_detected(self, db_session):
        from models import ProductCategory
        from forms import ProductCategoryForm
        a = ProductCategory(name="A")
        b = ProductCategory(name="B", parent=a)
        c = ProductCategory(name="C", parent=b)
        db_session.add_all([a, b, c])
        db_session.commit()
        # Trying to set A's parent to C would create loop
        form = ProductCategoryForm(
            _fd(id=str(a.id), name="A",
                parent_id=str(c.id), is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_valid_parent_relation(self, db_session):
        from models import ProductCategory
        from forms import ProductCategoryForm
        parent = ProductCategory(name="Parent")
        db_session.add(parent)
        db_session.commit()
        form = ProductCategoryForm(
            _fd(name="Child", parent_id=str(parent.id), is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_apply_to(self, db_session):
        from models import ProductCategory
        from forms import ProductCategoryForm
        form = ProductCategoryForm(
            _fd(name="Applied Cat", description="desc", is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        cat = ProductCategory()
        form.apply_to(cat)
        assert cat.name == "Applied Cat"
        assert cat.description == "desc"
        assert cat.is_active is True

    def test_description_max_length(self, db_session):
        from forms import ProductCategoryForm
        form = ProductCategoryForm(
            _fd(name="Cat", description="x" * 2001, is_active="y"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "description" in form.errors


class TestProductForm:
    FORM_META = {"csrf": False}

    def _cat(self, db_session, name="Default Category"):
        from models import ProductCategory
        c = ProductCategory(name=name)
        db_session.add(c)
        db_session.commit()
        return c

    def _fd_with_cat(self, db_session, cat_name="Cat", **kw):
        cat = self._cat(db_session, cat_name)
        data = dict(
            name="Test Product", price="100",
            purchase_price="50", currency="ILS",
            condition="USED", category_id=str(cat.id),
        )
        data.update(kw)
        return _fd(**data)

    def test_valid_form(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, name="Valid Product"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_missing_name(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, name=""),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_missing_price(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, price=""),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "price" in form.errors

    def test_missing_currency(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, currency=""),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "currency" in form.errors

    def test_missing_category(self, db_session):
        from forms import ProductForm
        cat = self._cat(db_session)
        form = ProductForm(
            _fd(name="NoCat", price="100", purchase_price="50",
                currency="ILS", condition="USED", category_id=""),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "category_id" in form.errors

    def test_name_max_length(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, name="x" * 256),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "name" in form.errors

    def test_price_below_purchase_price(self, db_session):
        from forms import ProductForm
        # price=30 < purchase_price=50 should fail
        form = ProductForm(
            self._fd_with_cat(db_session, price="30"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_selling_price_below_purchase(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, selling_price="20"),
            meta=self.FORM_META,
        )
        form.purchase_price.data = Decimal("50")
        form.price.data = Decimal("100")
        assert form.validate() is False

    def test_min_price_above_base_price(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, min_price="150"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_min_max_price_conflict(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, min_price="200", max_price="100"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_reorder_below_min_qty(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session,
                              reorder_point="5", min_qty="10"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_valid_reorder_point(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session,
                              reorder_point="10", min_qty="5"),
            meta=self.FORM_META,
        )
        assert form.validate() is True

    def test_negative_price_rejected(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, price="-1"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_negative_purchase_price_rejected(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, purchase_price="-1"),
            meta=self.FORM_META,
        )
        assert form.validate() is False

    def test_barcode_too_short(self, db_session):
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, barcode="123"),
            meta=self.FORM_META,
        )
        assert form.validate() is False
        assert "barcode" in form.errors

    def test_apply_to_basic(self, db_session):
        from models import Product
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, name="Applied",
                              sku="SKU001", brand="TestBrand"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        p = Product()
        form.apply_to(p)
        assert p.name == "Applied"
        assert p.sku == "SKU001"
        assert p.brand == "TestBrand"
        assert p.price == Decimal("100.00")
        assert p.purchase_price == Decimal("50.00")

    def test_apply_to_currency_defaults(self, db_session):
        from models import Product
        from forms import ProductForm
        form = ProductForm(
            self._fd_with_cat(db_session, currency="USD"),
            meta=self.FORM_META,
        )
        assert form.validate() is True
        p = Product()
        form.apply_to(p)
        assert p.currency == "USD"

