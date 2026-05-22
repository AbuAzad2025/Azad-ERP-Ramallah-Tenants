"""
إدارة الفترات المحاسبية — إقفال شهري / ربع سنوي / نصف سنوي / سنوي + ترحيل.
"""
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from extensions import db
from models import FiscalPeriod, PeriodClose, EntityPeriodBalance, SystemSettings
from permissions_config.enums import SystemPermissions
from utils import permission_required
from utils.fiscal_calendar import AR_PERIOD_LABELS, PERIOD_TYPES_ORDER
from utils.period_close_service import (
    close_fiscal_period,
    generate_closing_entries_for_period,
    period_to_dict,
    reopen_fiscal_period,
    sync_fiscal_periods,
)

fiscal_periods_bp = Blueprint(
    "fiscal_periods_bp", __name__, url_prefix="/security/fiscal-periods"
)


@fiscal_periods_bp.route("/")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def index():
    fiscal_year = request.args.get("year", datetime.now().year, type=int)
    period_type = request.args.get("type", "")
    return render_template(
        "fiscal_periods/index.html",
        fiscal_year=fiscal_year,
        period_type=period_type,
        period_labels=AR_PERIOD_LABELS,
        period_types=PERIOD_TYPES_ORDER,
    )


@fiscal_periods_bp.route("/api/list")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
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


@fiscal_periods_bp.route("/api/sync", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
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


@fiscal_periods_bp.route("/api/<int:period_id>/preview-close", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_preview_close(period_id):
    try:
        result = generate_closing_entries_for_period(period_id)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@fiscal_periods_bp.route("/api/<int:period_id>/close", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_close(period_id):
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


@fiscal_periods_bp.route("/api/<int:period_id>/reopen", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_reopen(period_id):
    try:
        uid = getattr(current_user, "id", None)
        result = reopen_fiscal_period(period_id, user_id=uid)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@fiscal_periods_bp.route("/api/<int:period_id>/snapshots")
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
def api_snapshots(period_id):
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


@fiscal_periods_bp.route("/api/settings", methods=["GET", "POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_LEDGER)
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
