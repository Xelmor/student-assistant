from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Subject
from ..dependencies import require_user, templates, validate_csrf

router = APIRouter()


@router.get('/subjects', response_class=HTMLResponse)
def subjects_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(request, 'subjects/subjects.html', {'user': user, 'subjects': subjects})


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
    subject = Subject(
        user_id=user.id,
        name=name,
        teacher=teacher or None,
        room=room or None,
        color=color,
        notes=notes or None,
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

    subject.name = name
    subject.teacher = teacher or None
    subject.room = room or None
    subject.color = color
    subject.notes = notes or None
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
