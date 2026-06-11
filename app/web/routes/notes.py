from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.validation import (
    normalize_bounded_text,
    normalize_external_url,
    safe_external_url,
    safe_hex_color,
)
from ...models import Note, Subject
from ..dependencies import require_user, templates, validate_csrf

router = APIRouter()


def build_notes_redirect(*, form_error: str | None = None, selected_note_id: int | None = None) -> str:
    params = {}
    if form_error:
        params['form_error'] = form_error
    if selected_note_id is not None:
        params['note'] = str(selected_note_id)
    query = urlencode(params)
    return f'/notes?{query}' if query else '/notes'


def parse_optional_subject_id(subject_id: str) -> int | None:
    normalized_subject_id = subject_id.strip()
    if not normalized_subject_id:
        return None
    if not normalized_subject_id.isdigit():
        raise ValueError('Не удалось определить выбранный предмет для заметки.')
    return int(normalized_subject_id)


@router.get('/notes', response_class=HTMLResponse)
def notes_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    form_error = request.query_params.get('form_error')
    selected_note_id = request.query_params.get('note')
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.created_at.desc()).all()
    for note in notes:
        note.safe_link = safe_external_url(note.link)
        note.safe_subject_color = safe_hex_color(
            note.subject.color if note.subject else None,
            default='#8b5cf6',
        )
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(
        request,
        'notes/notes.html',
        {
            'user': user,
            'notes': notes,
            'subjects': subjects,
            'form_error': form_error,
            'selected_note_id': int(selected_note_id) if selected_note_id and selected_note_id.isdigit() else None,
        }
    )


@router.post('/notes/add')
def add_note(
    request: Request,
    title: str = Form(...),
    content: str = Form(''),
    link: str = Form(''),
    subject_id: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    try:
        subject_id_value = parse_optional_subject_id(subject_id)
        normalized_title = normalize_bounded_text(
            title,
            label='Заголовок заметки',
            max_length=150,
            required=True,
        )
        normalized_content = normalize_bounded_text(
            content,
            label='Текст заметки',
            max_length=10000,
        )
        normalized_link = normalize_external_url(link)
    except ValueError as error:
        return RedirectResponse(build_notes_redirect(form_error=str(error)), status_code=302)

    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse(
                build_notes_redirect(form_error='Выбранный предмет для заметки не найден.'),
                status_code=302,
            )

    note = Note(
        user_id=user.id,
        subject_id=subject_id_value,
        title=normalized_title,
        content=normalized_content,
        link=normalized_link,
    )
    db.add(note)
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.post('/notes/edit/{note_id}')
@router.post('/notes/edit/{note_id}/')
def edit_note(
    note_id: int,
    request: Request,
    title: str = Form(...),
    content: str = Form(''),
    link: str = Form(''),
    subject_id: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if not note:
        return RedirectResponse('/notes', status_code=302)

    try:
        subject_id_value = parse_optional_subject_id(subject_id)
        normalized_title = normalize_bounded_text(
            title,
            label='Заголовок заметки',
            max_length=150,
            required=True,
        )
        normalized_content = normalize_bounded_text(
            content,
            label='Текст заметки',
            max_length=10000,
        )
        normalized_link = normalize_external_url(link)
    except ValueError as error:
        return RedirectResponse(
            build_notes_redirect(form_error=str(error), selected_note_id=note_id),
            status_code=302,
        )

    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse(
                build_notes_redirect(
                    form_error='Выбранный предмет для заметки не найден.',
                    selected_note_id=note_id,
                ),
                status_code=302,
            )

    note.title = normalized_title
    note.content = normalized_content
    note.link = normalized_link
    note.subject_id = subject_id_value
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.get('/notes/edit/{note_id}')
@router.get('/notes/edit/{note_id}/')
def edit_note_fallback(
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    return RedirectResponse('/notes', status_code=302)


@router.post('/notes/delete/{note_id}')
def delete_note(note_id: int, request: Request, _: None = Depends(validate_csrf), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if note:
        db.delete(note)
        db.commit()
    return RedirectResponse('/notes', status_code=302)
