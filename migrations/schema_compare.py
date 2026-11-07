"""Alembic compare hooks — reduce false drift vs production PostgreSQL."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import Enum as SAEnum

try:
    from sqlalchemy.dialects.postgresql import ENUM as PGEnum
except ImportError:  # pragma: no cover
    PGEnum = ()


def include_object(object_, name, type_, reflected, compare_to):
    # Runtime + scripts manage indexes (ensure_performance_indexes).
    if type_ == "index":
        return False
    # PG stores uniques as named constraints; SQLAlchemy often uses Column(unique=True).
    if type_ == "unique_constraint" and reflected and compare_to is None:
        return False
    # ondelete/onupdate differences on restored production DBs are not worth auto-migrating.
    if type_ == "foreign_key_constraint":
        return False
    return True


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    """Return False when DB type matches model (Alembic 1.9+ semantics)."""
    if PGEnum and isinstance(inspected_type, PGEnum) and isinstance(metadata_type, SAEnum):
        return False
    if isinstance(metadata_type, SAEnum):
        if getattr(metadata_type, "native_enum", True) is False:
            if isinstance(inspected_type, (sa.String, sa.VARCHAR)):
                return False
            if isinstance(inspected_type, SAEnum):
                return False
            if PGEnum and isinstance(inspected_type, PGEnum):
                return False
    if isinstance(inspected_type, SAEnum) and isinstance(metadata_type, SAEnum):
        return False
    if isinstance(inspected_type, (sa.VARCHAR, sa.String)) and isinstance(
        metadata_type, (sa.VARCHAR, sa.String)
    ):
        inspected_len = getattr(inspected_type, "length", None)
        meta_len = getattr(metadata_type, "length", None)
        if inspected_len and meta_len and inspected_len <= meta_len:
            return False
    return None


def get_configure_args():
    return {
        "include_object": include_object,
        # Production PG stores many enums as VARCHAR / PG ENUM; ORM uses native_enum=False.
        "compare_type": False,
        "compare_server_default": False,
    }
