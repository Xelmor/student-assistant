from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.validation import normalize_bounded_text, normalize_hex_color, safe_hex_color
from ...models import Subject
from ..dependencies import require_user, templates, validate_csrf

router = APIRouter()


def subjects_redirect(error: str | None = None) -> str:
    return f'/subjects?{urlencode({"form_error": error})}' if error else '/subjects'


def normalize_subject_fields(name: str, teacher: str, room: str, color: str, notes: str):
    return {
        'name': normalize_bounded_text(name, label='Название', max_length=100, required=True),
        'teacher': normalize_bounded_text(teacher, label='Преподаватель', max_length=100),
        'room': normalize_bounded_text(room, label='Аудитория', max_length=50),
        'color': normalize_hex_color(color),
        'notes': normalize_bounded_text(notes, label='Заметка', max_length=5000),
    }


@router.get('/subjects', response_class=HTMLResponse)
def subjects_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    for subject in subjects:
        subject.safe_color = safe_hex_color(subject.color)
    return templates.TemplateResponse(
        request,
        'subjects/subjects.html',
        {
            'user': user,
            'subjects': subjects,
            'form_error': request.query_params.get('form_error'),
        },
    )


@router.post('/subjects/add')
def add_subject(
    request: Request,
    name: str = Form(...),
    teacher: str = Form(''),
    room: str = Form(''),
    color: str = Form('#0d6efd'),
    notes: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    try:
        fields = normalize_subject_fields(name, teacher, room, color, notes)
    except ValueError as error:
        return RedirectResponse(subjects_redirect(str(error)), status_code=302)
    subject = Subject(
        user_id=user.id,
        **fields,
    )
    db.add(subject)
    db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.post('/subjects/edit/{subject_id}')
def edit_subject(
    subject_id: int,
    request: Request,
    name: str = Form(...),
    teacher: str = Form(''),
    room: str = Form(''),
    color: str = Form('#0d6efd'),
    notes: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
    if not subject:
        return RedirectResponse('/subjects', status_code=302)

    try:
        fields = normalize_subject_fields(name, teacher, room, color, notes)
    except ValueError as error:
        return RedirectResponse(subjects_redirect(str(error)), status_code=302)
    for field, value in fields.items():
        setattr(subject, field, value)
    db.commit()
    return RedirectResponse('/subjects', status_code=302)


@router.post('/subjects/delete/{subject_id}')
def delete_subject(subject_id: int, request: Request, _: None = Depends(validate_csrf), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
    if subject:
        db.delete(subject)
        db.commit()
    return RedirectResponse('/subjects', status_code=302)
