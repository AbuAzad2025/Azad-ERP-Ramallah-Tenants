from decimal import Decimal
import pytest


class TestProductCategoryModel:

    def test_create_category(self, db_session):
        from models import ProductCategory
        c = ProductCategory(name="Engine Parts")
        db_session.add(c)
        db_session.commit()
        assert c.id is not None
        assert c.name == "Engine Parts"
        assert repr(c) == "<ProductCategory Engine Parts>"

    def test_category_name_stripped(self, db_session):
        from models import ProductCategory
        c = ProductCategory(name="  Brake Pads  ")
        db_session.add(c)
        db_session.commit()
        assert c.name == "Brake Pads"

    def test_category_parent_relationship(self, db_session):
        from models import ProductCategory
        parent = ProductCategory(name="Auto Parts")
        db_session.add(parent)
        db_session.flush()
        child = ProductCategory(name="Oil Filters", parent_id=parent.id)
        db_session.add(child)
        db_session.commit()
        assert child.parent.name == "Auto Parts"
        assert parent.subcategories == [child]

    def test_category_products_relationship(self, db_session):
        from models import ProductCategory, Product
        cat = ProductCategory(name="Tyres")
        db_session.add(cat)
        db_session.flush()
        p = Product(name="Summer Tyre 205/55R16", category_id=cat.id)
        db_session.add(p)
        db_session.commit()
        assert p.category.name == "Tyres"
        assert cat.products == [p]


class TestProductModel:

    def test_create_minimal_product(self, db_session):
        from models import Product
        p = Product(name="test product")
        db_session.add(p)
        db_session.commit()
        assert p.id is not None
        assert p.name == "test product"
        assert p.condition == "NEW"
        assert p.is_digital is False
        assert p.tax_rate == 0
        assert p.min_qty == 0

    def test_product_currency_default(self, db_session):
        from models import Product
        p = Product(name="ILS Product")
        db_session.add(p)
        db_session.commit()
        assert p.currency == "ILS"

    def test_product_currency_uppercased(self, db_session):
        from models import Product
        p = Product(name="USD Product", currency="usd")
        db_session.add(p)
        db_session.commit()
        assert p.currency == "USD"

    def test_product_price_negative_raises(self, db_session):
        from models import Product
        with pytest.raises(ValueError, match="لا يمكن أن يكون سالباً"):
            Product(name="Neg Price", price=Decimal("-10.00"))

    def test_product_purchase_price_negative_raises(self, db_session):
        from models import Product
        with pytest.raises(ValueError, match="لا يمكن أن يكون سالباً"):
            Product(name="Neg Purchase", purchase_price=Decimal("-5.00"))

    def test_product_tax_rate_out_of_range(self, db_session):
        from models import Product
        with pytest.raises(ValueError, match="نسبة الضريبة"):
            Product(name="Bad Tax", tax_rate=Decimal("150.00"))

    def test_product_tax_rate_negative_raises(self, db_session):
        from models import Product
        with pytest.raises(ValueError, match="نسبة الضريبة"):
            Product(name="Neg Tax", tax_rate=Decimal("-10.00"))

    def test_product_min_qty_default(self, db_session):
        from models import Product
        p = Product(name="Default Min")
        db_session.add(p)
        db_session.commit()
        assert p.min_qty == 0

    def test_product_min_qty_negative_raises(self, db_session):
        from models import Product
        with pytest.raises(ValueError, match="الحد الأدنى للكمية"):
            Product(name="Neg MinQty", min_qty=-5)

    def test_product_reorder_point_negative_raises(self, db_session):
        from models import Product
        with pytest.raises(ValueError, match="نقطة إعادة الطلب"):
            Product(name="Neg Reorder", reorder_point=-1)

    def test_product_warranty_negative_raises(self, db_session):
        from models import Product
        with pytest.raises(ValueError, match="فترة الضمان"):
            Product(name="Neg Warranty", warranty_period=-1)

    def test_product_name_stripped(self, db_session):
        from models import Product
        p = Product(name="  Stripped Product  ")
        db_session.add(p)
        db_session.commit()
        assert p.name == "Stripped Product"

    def test_product_sku_uppercased(self, db_session):
        from models import Product
        p = Product(name="SKU Test", sku=" sku-123 ")
        db_session.add(p)
        db_session.commit()
        assert p.sku == "SKU-123"

    def test_product_serial_no_uppercased(self, db_session):
        from models import Product
        p = Product(name="Serial Test", serial_no=" sn-456 ")
        db_session.add(p)
        db_session.commit()
        assert p.serial_no == "SN-456"

    def test_product_condition_new_default(self, db_session):
        from models import Product
        p = Product(name="New Condition")
        db_session.add(p)
        db_session.commit()
        assert p.condition_display == "جديد"

    def test_product_condition_used(self, db_session):
        from models import Product
        p = Product(name="Used Condition", condition="USED")
        db_session.add(p)
        db_session.commit()
        assert p.condition_display == "مستعمل"

    def test_product_effective_name_fallback(self, db_session):
        from models import Product
        p = Product(name="Basic Name")
        db_session.add(p)
        db_session.commit()
        assert p.effective_name == "Basic Name"

    def test_product_effective_name_online(self, db_session):
        from models import Product
        p = Product(name="Basic Name", online_name="Online Name")
        db_session.add(p)
        db_session.commit()
        assert p.effective_name == "Online Name"

    def test_product_effective_price_defaults_to_online_price(self, db_session):
        from models import Product
        p = Product(name="Default Price")
        db_session.add(p)
        db_session.commit()
        assert p.effective_price == 0

    def test_product_effective_price_online(self, db_session):
        from models import Product
        p = Product(name="Online Price", price=Decimal("100.00"), online_price=Decimal("90.00"))
        db_session.add(p)
        db_session.commit()
        assert p.effective_price == 90.00

    def test_product_effective_image_fallback(self, db_session):
        from models import Product
        p = Product(name="Image Fallback", image="img1.jpg")
        db_session.add(p)
        db_session.commit()
        assert p.effective_image == "img1.jpg"

    def test_product_effective_image_online(self, db_session):
        from models import Product
        p = Product(name="Online Image", image="img1.jpg", online_image="online.jpg")
        db_session.add(p)
        db_session.commit()
        assert p.effective_image == "online.jpg"

    def test_product_repr(self, db_session):
        from models import Product
        p = Product(name="Repr Product")
        db_session.add(p)
        db_session.commit()
        assert repr(p) == "<Product Repr Product>"

    def test_product_default_timestamps(self, db_session):
        from models import Product
        p = Product(name="Timestamps")
        db_session.add(p)
        db_session.commit()
        assert p.created_at is not None
        assert p.updated_at is not None

    def test_product_default_price_fields(self, db_session):
        from models import Product
        p = Product(name="Default Prices")
        db_session.add(p)
        db_session.commit()
        assert p.purchase_price == 0
        assert p.selling_price == 0
        assert p.price == 0
        assert p.cost_before_shipping == 0
        assert p.cost_after_shipping == 0
