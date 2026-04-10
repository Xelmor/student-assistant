from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Subject, Task
from .common import require_user, templates

router = APIRouter()


@router.get('/tasks', response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    tasks = db.query(Task).filter(Task.user_id == user.id).order_by(Task.is_completed.asc(), Task.deadline.asc()).all()
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    return templates.TemplateResponse(
        request,
        'tasks.html',
        {
            'user': user,
            'tasks': tasks,
            'subjects': subjects,
            'now': datetime.now(),
        }
    )


@router.post('/tasks/add')
def add_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    deadline_value = datetime.strptime(deadline, '%Y-%m-%dT%H:%M') if deadline else None
    task = Task(
        user_id=user.id,
        subject_id=subject_id if subject_id else None,
        title=title,
        description=description or None,
        deadline=deadline_value,
        priority=priority,
        difficulty=difficulty,
    )
    db.add(task)
    db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.post('/tasks/edit/{task_id}')
def edit_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        return RedirectResponse('/tasks', status_code=302)

    if subject_id:
        subject = db.query(Subject).filter(Subject.id == subject_id, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse('/tasks', status_code=302)

    task.title = title
    task.description = description or None
    task.subject_id = subject_id if subject_id else None
    task.deadline = datetime.strptime(deadline, '%Y-%m-%dT%H:%M') if deadline else None
    task.priority = priority
    task.difficulty = difficulty
    db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.get('/tasks/toggle/{task_id}')
def toggle_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        task.is_completed = not task.is_completed
        db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.get('/tasks/delete/{task_id}')
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse('/tasks', status_code=302)
