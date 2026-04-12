from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Subject, Task
from .common import require_user, templates, validate_csrf

router = APIRouter()


@router.get('/tasks', response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    selected_task_id = request.query_params.get('task')
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
            'selected_task_id': int(selected_task_id) if selected_task_id and selected_task_id.isdigit() else None,
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
    _: None = Depends(validate_csrf),
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


@router.post('/tasks/quick-add')
def quick_add_task(
    request: Request,
    title: str = Form(...),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return JSONResponse({'ok': False, 'error': 'auth'}, status_code=401)

    normalized_title = title.strip()
    if not normalized_title:
        return JSONResponse({'ok': False, 'error': 'title'}, status_code=422)

    task = Task(
        user_id=user.id,
        title=normalized_title,
        priority='medium',
        difficulty='medium',
        is_completed=False,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    pending_count = db.query(Task).filter(Task.user_id == user.id, Task.is_completed.is_(False)).count()
    return JSONResponse(
        {
            'ok': True,
            'task': {
                'id': task.id,
                'title': task.title,
            },
            'pending_count': pending_count,
        }
    )


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
    _: None = Depends(validate_csrf),
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


@router.post('/tasks/toggle/{task_id}')
def toggle_task(task_id: int, request: Request, _: None = Depends(validate_csrf), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        task.is_completed = not task.is_completed
        task.completed_at = datetime.now() if task.is_completed else None
        db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.post('/tasks/delete/{task_id}')
def delete_task(task_id: int, request: Request, _: None = Depends(validate_csrf), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse('/tasks', status_code=302)
