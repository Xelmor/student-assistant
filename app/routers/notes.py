from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Note, Subject
from .common import require_user, templates

router = APIRouter()


@router.get('/notes', response_class=HTMLResponse)
def notes_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.created_at.desc()).all()
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(
        request,
        'notes.html',
        {
            'user': user,
            'notes': notes,
            'subjects': subjects,
        }
    )


@router.post('/notes/add')
def add_note(
    request: Request,
    title: str = Form(...),
    content: str = Form(''),
    link: str = Form(''),
    subject_id: str = Form(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    subject_id_value = int(subject_id) if subject_id else None
    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/notes', status_code=302)

    note = Note(
        user_id=user.id,
        subject_id=subject_id_value,
        title=title,
        content=content or None,
        link=link or None,
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
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if not note:
        return RedirectResponse('/notes', status_code=302)

    subject_id_value = int(subject_id) if subject_id else None
    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/notes', status_code=302)

    note.title = title
    note.content = content or None
    note.link = link or None
    note.subject_id = subject_id_value
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.get('/notes/edit/{note_id}')
@router.get('/notes/edit/{note_id}/')
def edit_note_fallback(
    note_id: int,
    request: Request,
    title: str | None = Query(None),
    content: str = Query(''),
    link: str = Query(''),
    subject_id: str = Query(''),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    if title is None:
        return RedirectResponse('/notes', status_code=302)

    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if not note:
        return RedirectResponse('/notes', status_code=302)

    subject_id_value = int(subject_id) if subject_id else None
    if subject_id_value:
        subject = db.query(Subject).filter(Subject.id == subject_id_value, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/notes', status_code=302)

    note.title = title
    note.content = content or None
    note.link = link or None
    note.subject_id = subject_id_value
    db.commit()
    return RedirectResponse('/notes', status_code=302)


@router.get('/notes/delete/{note_id}')
def delete_note(note_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).first()
    if note:
        db.delete(note)
        db.commit()
    return RedirectResponse('/notes', status_code=302)
