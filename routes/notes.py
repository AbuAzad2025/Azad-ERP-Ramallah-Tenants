
# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for, abort, current_app
from flask_login import current_user, login_required
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from extensions import db
from forms import NoteForm
from models import Note
import utils
from utils import _get_or_404

notes_bp = Blueprint('notes_bp', __name__, url_prefix='/notes', template_folder='templates/notes')

ENTITY_TYPES = [
    ('', '-- اختر --'),
    ('CUSTOMER', 'عميل'),
    ('SALE', 'بيع'),
    ('PRODUCT', 'منتج'),
    ('SUPPLIER', 'مورد'),
    ('PARTNER', 'شريك'),
    ('INVOICE', 'فاتورة'),
    ('SHIPMENT', 'شحنة'),
    ('SERVICE', 'صيانة'),
    ('USER', 'مستخدم'),
    ('OTHER', 'أخرى')
]

def _coalesce_entity(form):
    etype = None
    eid = None
    if hasattr(form, 'entity_type') and form.entity_type.data:
        etype = (form.entity_type.data or '').strip() or None
    else:
        etype = (request.values.get('entity_type') or '').strip() or None
    if hasattr(form, 'entity_id') and form.entity_id.data:
        try:
            eid = int(form.entity_id.data) if str(form.entity_id.data).strip() != '' else None
        except Exception:
            eid = None
    else:
        eid = request.values.get('entity_id', type=int)
    return etype, eid

@notes_bp.route('/', methods=['GET'], endpoint='list_notes')
@login_required
def list_notes():
    etype = request.args.get('entity_type')
    eid = request.args.get('entity_id', type=int)
    pinned = request.args.get('is_pinned')
    prio = request.args.get('priority')
    q = Note.query.options(joinedload(Note.author))

    fs = []
    if etype:
        fs.append(Note.entity_type == etype)
    if eid:
        fs.append(Note.entity_id == eid)
    if pinned in ('0', '1'):
        fs.append(Note.is_pinned == (pinned == '1'))
    if prio:
        fs.append(Note.priority == prio)
    if fs:
        q = q.filter(and_(*fs))

    q = q.order_by(Note.is_pinned.desc(), Note.created_at.desc())
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    notes = pagination.items

    if request.args.get('format') == 'json' or request.is_json:
        data = [{
            'id': n.id,
            'content': n.content,
            'author': (n.author.username if n.author else None),
            'entity_type': n.entity_type,
            'entity_id': n.entity_id,
            'is_pinned': n.is_pinned,
            'priority': n.priority,
            'created_at': n.created_at.isoformat()
        } for n in notes]
        return jsonify({
            'data': data,
            'meta': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        })

    form = NoteForm()
    form.entity_type.choices = ENTITY_TYPES
    return render_template(
        'notes/list.html',
        notes=notes,
        pagination=pagination,
        filters={'entity_type': etype, 'entity_id': eid, 'is_pinned': pinned, 'priority': prio},
        form=form,
        entity_choices=ENTITY_TYPES
    )

@notes_bp.route('/new', methods=['GET', 'POST'], endpoint='create_note')
@login_required
def create_note():
    form = NoteForm()
    form.entity_type.choices = ENTITY_TYPES

    if request.method == 'GET':
        pre_etype = (request.args.get('entity_type') or '').strip() or None
        pre_eid = request.args.get('entity_id', type=int)
        if hasattr(form, 'entity_type') and pre_etype is not None:
            form.entity_type.data = pre_etype
        if hasattr(form, 'entity_id') and pre_eid is not None:
            form.entity_id.data = pre_eid
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render_template('notes/_form.html', form=form, entity_choices=ENTITY_TYPES, mode='create')
        return redirect(url_for('notes_bp.list_notes'))

    if not form.validate_on_submit():
        errors = {f: errs[0] for f, errs in form.errors.items()}
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, errors=errors), 400
        flash('فشل إضافة الملاحظة: ' + ', '.join(errors.values()), 'danger')
        return redirect(url_for('notes_bp.list_notes'))

    etype, eid = _coalesce_entity(form)

    note = Note(
        content=form.content.data.strip(),
        author_id=current_user.id,
        entity_type=etype,
        entity_id=eid,
        is_pinned=form.is_pinned.data,
        priority=form.priority.data,
        target_type=form.target_type.data,
        target_ids=form.target_ids.data,
        notification_type=form.notification_type.data,
        notification_date=form.notification_date.data,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.session.add(note)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, error='حدث خطأ داخلي'), 500
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('notes_bp.list_notes'))

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'note': {
                'id': note.id,
                'content': note.content,
                'author': current_user.username,
                'entity_type': note.entity_type,
                'entity_id': note.entity_id,
                'is_pinned': note.is_pinned,
                'priority': note.priority,
                'created_at': note.created_at.strftime('%Y-%m-%d %H:%M')
            }
        }), 201

    flash('تم إضافة الملاحظة بنجاح.', 'success')
    return redirect(url_for('notes_bp.list_notes'))

@notes_bp.route('/<int:note_id>', methods=['GET'], endpoint='note_detail')
@login_required
def note_detail(note_id):
    note = _get_or_404(Note, note_id, load_options=[joinedload(Note.author)])
    return render_template('notes/detail.html', note=note)

@notes_bp.route('/<int:note_id>/edit', methods=['GET'], endpoint='edit_note')
@login_required
def edit_note(note_id):
    note = _get_or_404(Note, note_id)
    form = NoteForm(obj=note)
    form.entity_type.choices = ENTITY_TYPES
    form.entity_id.data = str(note.entity_id or '') if hasattr(form, 'entity_id') else ''
    return render_template('notes/_form.html', form=form, entity_choices=ENTITY_TYPES, mode='edit', note_id=note.id)

@notes_bp.route('/<int:note_id>', methods=['POST', 'PATCH'], endpoint='update_note')
@login_required
def update_note(note_id):
    note = _get_or_404(Note, note_id)
    form = NoteForm()
    form.entity_type.choices = ENTITY_TYPES

    if not form.validate_on_submit():
        errors = {f: errs[0] for f, errs in form.errors.items()}
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, errors=errors), 400
        flash('فشل تعديل الملاحظة: ' + ', '.join(errors.values()), 'danger')
        return redirect(url_for('notes_bp.list_notes'))

    etype, eid = _coalesce_entity(form)

    note.content = form.content.data.strip()
    note.entity_type = etype
    note.entity_id = eid
    note.is_pinned = form.is_pinned.data
    note.priority = form.priority.data

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, error='حدث خطأ داخلي'), 500
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('notes_bp.list_notes'))

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'note': {
                'id': note.id,
                'content': note.content,
                'author': (note.author.username if note.author else None),
                'entity_type': note.entity_type,
                'entity_id': note.entity_id,
                'is_pinned': note.is_pinned,
                'priority': note.priority,
                'created_at': note.created_at.strftime('%Y-%m-%d %H:%M')
            }
        })

    flash('تم تحديث الملاحظة.', 'success')
    return redirect(url_for('notes_bp.list_notes'))

@notes_bp.route('/<int:note_id>/delete', methods=['POST', 'DELETE'], endpoint='delete_note')
@login_required
def delete_note(note_id):
    note = _get_or_404(Note, note_id)
    db.session.delete(note)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, error='حدث خطأ داخلي'), 500
        flash('حدث خطأ داخلي', 'danger')
        return redirect(url_for('notes_bp.list_notes'))

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'deleted_id': note_id})

    flash('تم حذف الملاحظة.', 'success')
    return redirect(url_for('notes_bp.list_notes'))

@notes_bp.route('/<int:note_id>/toggle-pin', methods=['POST'], endpoint='toggle_pin')
@login_required
def toggle_pin(note_id):
    note = _get_or_404(Note, note_id)
    note.is_pinned = not bool(note.is_pinned)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('internal error')
        return jsonify(success=False, error='حدث خطأ داخلي'), 500
    return jsonify({'success': True, 'note_id': note.id, 'is_pinned': note.is_pinned})
