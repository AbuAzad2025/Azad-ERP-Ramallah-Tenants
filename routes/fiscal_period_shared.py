"""منطق مشترك لإقفال الفترات — منصة (/security) وتينانت (/console)."""
from __future__ import annotations

from datetime import datetime

from flask import jsonify, render_template, request, url_for
from flask_login import current_user

from extensions import db
from models import FiscalPeriod, PeriodClose, EntityPeriodBalance, SystemSettings
from utils.fiscal_calendar import AR_PERIOD_LABELS, PERIOD_TYPES_ORDER
from utils.period_close_service import (
    close_fiscal_period,
    generate_closing_entries_for_period,
    period_to_dict,
    reopen_fiscal_period,
    sync_fiscal_periods,
)


def _api_urls(endpoint_prefix: str) -> dict:
    """روابط API للقالب (بدون مسارات /security ثابتة)."""
    base = url_for(f"{endpoint_prefix}.api_list").rsplit("/api/list", 1)[0]
    return {
        "api_list": url_for(f"{endpoint_prefix}.api_list"),
        "api_sync": url_for(f"{endpoint_prefix}.api_sync"),
        "api_settings": url_for(f"{endpoint_prefix}.api_settings"),
        "api_base": base,
    }


def render_index(*, endpoint_prefix: str, tenant_slug: str | None = None):
    fiscal_year = request.args.get("year", datetime.now().year, type=int)
    period_type = request.args.get("type", "")
    return render_template(
        "fiscal_periods/index.html",
        fiscal_year=fiscal_year,
        period_type=period_type,
        period_labels=AR_PERIOD_LABELS,
        period_types=PERIOD_TYPES_ORDER,
        tenant_slug=tenant_slug,
        hub_url=url_for("tenant_console.index") if tenant_slug else url_for("ledger_control.index"),
        hub_label="لوحة التينانت" if tenant_slug else "دفتر الأستاذ",
        **_api_urls(endpoint_prefix),
    )


def api_list():
    fy = request.args.get("fiscal_year", type=int)
    ptype = request.args.get("period_type", "").strip().upper()
    q = FiscalPeriod.query.order_by(FiscalPeriod.start_date.desc())
    if fy:
        q = q.filter(FiscalPeriod.fiscal_year == fy)
    if ptype:
        q = q.filter(FiscalPeriod.period_type == ptype)
    periods = [period_to_dict(p) for p in q.limit(200).all()]
    return jsonify({"success": True, "periods": periods})


def api_sync():
    data = request.get_json(silent=True) or {}
    stats = sync_fiscal_periods(
        from_year=data.get("from_year"),
        to_year=data.get("to_year"),
        include_monthly=data.get("include_monthly", True),
        include_quarterly=data.get("include_quarterly", True),
        include_half=data.get("include_half", True),
        include_year=data.get("include_year", True),
    )
    return jsonify({"success": True, **stats})


def api_preview_close(period_id: int):
    try:
        result = generate_closing_entries_for_period(period_id)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


def api_close(period_id: int):
    data = request.get_json(silent=True) or {}
    try:
        uid = getattr(current_user, "id", None)
        result = close_fiscal_period(
            period_id,
            user_id=uid,
            close_scope=data.get("close_scope", "FULL"),
            post_gl=data.get("post_gl", True),
            carry_forward=data.get("carry_forward", True),
            lock_period=data.get("lock_period", True),
            notes=data.get("notes"),
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


def api_reopen(period_id: int):
    try:
        uid = getattr(current_user, "id", None)
        result = reopen_fiscal_period(period_id, user_id=uid)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


def api_snapshots(period_id: int):
    limit = request.args.get("limit", 50, type=int)
    entity_type = request.args.get("entity_type", "").upper()
    q = EntityPeriodBalance.query.filter_by(fiscal_period_id=period_id)
    if entity_type:
        q = q.filter(EntityPeriodBalance.entity_type == entity_type)
    rows = q.order_by(EntityPeriodBalance.closing_balance.desc()).limit(limit).all()
    return jsonify({
        "success": True,
        "snapshots": [
            {
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "closing_balance": float(r.closing_balance or 0),
                "currency": r.currency,
                "applied_to_opening": r.applied_to_opening,
            }
            for r in rows
        ],
    })


def api_settings():
    if request.method == "GET":
        return jsonify({
            "success": True,
            "annual_carry_updates_opening_balance": bool(
                SystemSettings.get_setting("annual_carry_updates_opening_balance", False)
            ),
        })
    data = request.get_json(silent=True) or {}
    if "annual_carry_updates_opening_balance" in data:
        SystemSettings.set_setting(
            "annual_carry_updates_opening_balance",
            bool(data["annual_carry_updates_opening_balance"]),
            data_type="boolean",
        )
    return jsonify({"success": True})
