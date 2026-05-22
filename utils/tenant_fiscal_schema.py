"""
جداول إقفال الفترات داخل كل schema تينانت (وليس public المشترك فقط).
"""
from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import text as sa_text

from extensions import db

FISCAL_TABLES = ("fiscal_periods", "period_closes", "entity_period_balances")


def _valid_schema(schema: str) -> str:
    s = (schema or "").strip()
    if not s or s.lower() == "public":
        return "public"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s) or len(s) > 63:
        raise ValueError(f"schema غير صالح: {schema}")
    return s


def _table_exists(session, schema: str, table: str) -> bool:
    return bool(
        session.execute(
            sa_text(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = :s AND table_name = :t
                """
            ),
            {"s": schema, "t": table},
        ).scalar()
    )


def ensure_fiscal_tables_in_schema(session, schema: str) -> dict:
    """
    ينسخ بنية جداول الإقفال من public إلى schema التينانت إن لم تكن موجودة.
    """
    schema = _valid_schema(schema)
    if schema == "public":
        return {"schema": schema, "created": [], "skipped": list(FISCAL_TABLES)}

    created = []
    skipped = []
    for table in FISCAL_TABLES:
        if not _table_exists(session, "public", table):
            raise RuntimeError(f"جدول public.{table} غير موجود — نفّذ flask db upgrade أولاً")
        if _table_exists(session, schema, table):
            skipped.append(table)
            continue
        session.execute(
            sa_text(
                f'CREATE TABLE "{schema}"."{table}" '
                f'(LIKE public."{table}" INCLUDING ALL INCLUDING INDEXES)'
            )
        )
        created.append(table)
    if created:
        session.commit()
    return {"schema": schema, "created": created, "skipped": skipped}


def set_local_search_path(session, schema: str) -> None:
    schema = _valid_schema(schema)
    if schema == "public":
        session.execute(sa_text("SET LOCAL search_path TO public"))
        return
    session.execute(sa_text(f'SET LOCAL search_path TO "{schema}", public'))


def ensure_fiscal_tables_for_request() -> None:
    """يُستدعى قبل عمليات الإقفال داخل جلسة تينانت."""
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return
        schema = str(getattr(g, "tenant_schema", "") or "").strip()
        if not schema or schema.lower() == "public":
            return
        ensure_fiscal_tables_in_schema(db.session, schema)
    except Exception:
        db.session.rollback()
        raise


def iter_tenant_schemas(session) -> Iterable[tuple[str, str]]:
    from models import TenantRegistry

    for row in TenantRegistry.query.filter_by(is_active=True).order_by(TenantRegistry.id).all():
        slug = (row.slug or "").strip().lower()
        schema = _valid_schema(row.schema_name or "public")
        yield slug, schema


def ensure_all_tenant_fiscal_tables(session) -> list[dict]:
    results = []
    for slug, schema in iter_tenant_schemas(session):
        if schema == "public":
            results.append({"slug": slug, "schema": schema, "note": "uses_public"})
            continue
        stats = ensure_fiscal_tables_in_schema(session, schema)
        stats["slug"] = slug
        results.append(stats)
    return results


def sync_fiscal_periods_all_tenants(**kwargs) -> list[dict]:
    """مزامنة الفترات لكل تينانت في schema الخاص به."""
    from utils.period_close_service import sync_fiscal_periods

    out = []
    for slug, schema in iter_tenant_schemas(db.session):
        set_local_search_path(db.session, schema)
        if schema != "public":
            ensure_fiscal_tables_in_schema(db.session, schema)
        stats = sync_fiscal_periods(**kwargs)
        stats["slug"] = slug
        stats["schema"] = schema
        out.append(stats)
    db.session.commit()
    return out
