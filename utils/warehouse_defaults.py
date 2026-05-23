"""افتراضي المستودع داخل التينانت — بدون الاعتماد على id=1."""

from __future__ import annotations


def get_default_warehouse_id() -> int | None:
    """أول مستودع نشط منطقي (إعدادات المتجر ثم ONLINE ثم أي نشط)."""
    try:
        from flask import current_app, has_request_context

        if not has_request_context():
            return None

        from extensions import db
        from models import Warehouse, WarehouseType

        default_id = current_app.config.get("SHOP_DEFAULT_WAREHOUSE_ID")
        if default_id:
            wh = db.session.get(Warehouse, int(default_id))
            if wh and getattr(wh, "is_active", True):
                return int(wh.id)

        online_val = (
            getattr(WarehouseType, "ONLINE").value
            if hasattr(WarehouseType, "ONLINE")
            else "ONLINE"
        )
        wh = (
            Warehouse.query.filter_by(is_active=True, online_is_default=True).first()
            or (
                Warehouse.query.filter_by(
                    is_active=True, warehouse_type=online_val
                ).first()
                if hasattr(Warehouse, "warehouse_type")
                else None
            )
            or Warehouse.query.filter_by(is_active=True).order_by(Warehouse.id).first()
        )
        return int(wh.id) if wh else None
    except Exception:
        return None
