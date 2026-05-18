
from permissions_config.enums import SystemPermissions
from flask import Blueprint, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Archive, Shipment, Check, CheckStatus
from utils import permission_required

archive_routes_bp = Blueprint('archive_routes', __name__)

@archive_routes_bp.route("/shipments/archive/<int:shipment_id>", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_SHIPMENTS)
def archive_shipment(shipment_id):
    
    try:
        shipment = db.get_or_404(Shipment, shipment_id)
        reason = request.form.get('reason', 'أرشفة تلقائية')
        
        archive = Archive.archive_record(
            record=shipment,
            reason=reason,
            user_id=current_user.id
        )
        from datetime import datetime
        shipment.is_archived = True
        from datetime import timezone
        shipment.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        shipment.archived_by = current_user.id
        shipment.archive_reason = reason
        db.session.commit()
        flash(f'تم أرشفة الشحنة رقم {shipment.id} بنجاح', 'success')
        return redirect(url_for('shipments_bp.list_shipments'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('shipments_bp.list_shipments'))

@archive_routes_bp.route("/checks/archive/<int:check_id>", methods=["POST"])
@login_required
@permission_required(SystemPermissions.MANAGE_PAYMENTS)
def archive_check(check_id):
    
    try:
        check = db.get_or_404(Check, check_id)
        reason = request.form.get('reason', 'أرشفة تلقائية')
        
        archive = Archive.archive_record(
            record=check,
            reason=reason,
            user_id=current_user.id
        )
        from datetime import datetime
        check.is_archived = True
        from datetime import timezone
        check.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        check.archived_by = current_user.id
        check.archive_reason = reason
        try:
            check.status = CheckStatus.ARCHIVED
        except Exception:
            check.status = CheckStatus.ARCHIVED.value
        db.session.commit()
        flash(f'تم أرشفة الشيك رقم {check.id} بنجاح', 'success')
        return redirect(url_for('checks.index'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        flash('حدث خطأ داخلي', 'error')
        return redirect(url_for('checks.index'))
