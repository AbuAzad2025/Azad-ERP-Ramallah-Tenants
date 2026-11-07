import os
import pytest
from datetime import datetime, timezone
from decimal import Decimal

os.environ["APP_ENV"] = "test"
os.environ["FLASK_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["WTF_CSRF_ENABLED"] = "false"
os.environ["AI_SYSTEMS_ENABLED"] = "false"
os.environ["ENABLE_AUTOMATED_BACKUPS"] = "false"
os.environ["PAYMENT_ALLOCATION_ENABLED"] = "false"
os.environ["AUTO_CREATE_PERFORMANCE_INDEXES"] = "false"
os.environ["SKIP_SYSTEM_INTEGRITY"] = "1"

from app import create_app
from extensions import db as _db
from sqlalchemy import event


@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {},
        "SERVER_NAME": "test.local",
        "AI_SYSTEMS_ENABLED": False,
        "ENABLE_AUTOMATED_BACKUPS": False,
        "PAYMENT_ALLOCATION_ENABLED": False,
        "AUTO_CREATE_PERFORMANCE_INDEXES": False,
        "SKIP_SYSTEM_INTEGRITY": True,
    })
    with app.app_context():
        yield app


@pytest.fixture(scope="function")
def db(app):
    _db.create_all()
    _seed_static_data(_db)
    yield _db
    _db.session.rollback()
    _db.session.remove()
    _db.drop_all()


def _seed_static_data(db):
    from models import Customer, Supplier, Partner
    existing = Customer.query.first()
    if existing:
        return
    db.session.add(Customer(
        id=1, name="test customer", phone="0500000001",
        current_balance=Decimal("500.00"), currency="ILS",
    ))
    db.session.add(Supplier(
        id=1, name="test supplier", phone="0500000002",
        current_balance=Decimal("300.00"), currency="ILS",
    ))
    db.session.add(Partner(
        id=1, name="test partner", phone_number="0500000003",
        current_balance=Decimal("200.00"), currency="ILS",
    ))
    db.session.commit()


@pytest.fixture(scope="function")
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="function", autouse=True)
def db_session(db):
    db.session.begin_nested()
    yield db.session
    db.session.rollback()
    db.session.expire_all()
