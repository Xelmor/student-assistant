from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.time import calculate_task_score, current_time
from ...models import Subject, Task
from ..dependencies import require_user, templates, validate_csrf

router = APIRouter()


def pluralize_days(value: int) -> str:
    if value % 10 == 1 and value % 100 != 11:
        return 'день'
    if value % 10 in {2, 3, 4} and value % 100 not in {12, 13, 14}:
        return 'дня'
    return 'дней'


def build_deadline_state(task: Task, now: datetime) -> dict[str, str | int | None]:
    if task.is_completed:
        return {
            'tone': 'done',
            'label': 'Выполнено',
            'detail': 'Задача закрыта',
            'sort_rank': -1,
        }

    if not task.deadline:
        return {
            'tone': 'neutral',
            'label': 'Без дедлайна',
            'detail': 'Срок не указан',
            'sort_rank': 0,
        }

    delta = task.deadline - now
    total_seconds = int(delta.total_seconds())
    abs_seconds = abs(total_seconds)
    abs_minutes = max(1, abs_seconds // 60)
    abs_hours = max(1, abs_seconds // 3600)
    abs_days = max(1, abs_seconds // 86400)

    if total_seconds < 0:
        if abs_seconds < 3600:
            detail = f'Просрочено на {abs_minutes} мин'
        elif abs_seconds < 86400:
            detail = f'Просрочено на {abs_hours} ч'
        else:
            detail = f'Просрочено на {abs_days} д'
        return {
            'tone': 'overdue',
            'label': 'Критично',
            'detail': detail,
            'sort_rank': 5,
        }

    if total_seconds <= 6 * 3600:
        return {
            'tone': 'danger',
            'label': 'Срочно',
            'detail': f'Осталось {abs_hours} ч',
            'sort_rank': 4,
        }

    if total_seconds <= 24 * 3600:
        return {
            'tone': 'danger',
            'label': 'Сегодня',
            'detail': f'До {task.deadline.strftime("%H:%M")}',
            'sort_rank': 4,
        }

    if total_seconds <= 2 * 86400:
        return {
            'tone': 'warn',
            'label': 'Риск',
            'detail': f'Осталось {abs_days} {pluralize_days(abs_days)}',
            'sort_rank': 3,
        }

    if total_seconds <= 7 * 86400:
        return {
            'tone': 'watch',
            'label': 'На неделе',
            'detail': f'Осталось {abs_days} {pluralize_days(abs_days)}',
            'sort_rank': 2,
        }

    return {
        'tone': 'safe',
        'label': 'Спокойно',
        'detail': f'До {task.deadline.strftime("%d.%m.%Y")}',
        'sort_rank': 1,
    }


def enrich_tasks(tasks: list[Task], now: datetime) -> list[Task]:
    for task in tasks:
        task.deadline_state = build_deadline_state(task, now)
        task.smart_score = calculate_task_score(task) if not task.is_completed else -1
        task.smart_deadline_text = (
            task.deadline.strftime('%d.%m.%Y %H:%M')
            if task.deadline else
            '—'
        )

    return sorted(
        tasks,
        key=lambda task: (
            task.is_completed,
            -int(task.deadline_state['sort_rank']),
            -int(task.smart_score),
            task.deadline or datetime.max,
            task.created_at or datetime.min,
        ),
    )


def build_task_groups(tasks: list[Task]) -> list[dict]:
    grouped: dict[int | None, dict] = {}

    for task in tasks:
        subject = task.subject
        group_key = subject.id if subject else None
        if group_key not in grouped:
            grouped[group_key] = {
                'key': group_key,
                'subject': subject,
                'title': subject.name if subject else 'Без предмета',
                'color': getattr(subject, 'color', '#d99a6c') if subject else '#d99a6c',
                'teacher': getattr(subject, 'teacher', None) if subject else None,
                'room': getattr(subject, 'room', None) if subject else None,
                'tasks': [],
                'pending_count': 0,
            }

        grouped[group_key]['tasks'].append(task)
        if not task.is_completed:
            grouped[group_key]['pending_count'] += 1

    groups = list(grouped.values())
    groups.sort(
        key=lambda group: (
            group['subject'] is None,
            group['title'].lower(),
        )
    )
    return groups


@router.get('/tasks', response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    selected_task_id = request.query_params.get('task')
    now = current_time().replace(tzinfo=None)
    raw_tasks = db.query(Task).filter(Task.user_id == user.id).all()
    tasks = enrich_tasks(raw_tasks, now)
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()

    smart_counts = {
        'overdue': sum(1 for task in tasks if not task.is_completed and task.deadline_state['tone'] == 'overdue'),
        'danger': sum(1 for task in tasks if not task.is_completed and task.deadline_state['tone'] == 'danger'),
        'warn': sum(1 for task in tasks if not task.is_completed and task.deadline_state['tone'] == 'warn'),
        'pending': sum(1 for task in tasks if not task.is_completed),
    }
    task_groups = build_task_groups(tasks)

    return templates.TemplateResponse(
        request,
        'tasks/tasks.html',
        {
            'user': user,
            'tasks': tasks,
            'subjects': subjects,
            'now': now,
            'smart_counts': smart_counts,
            'task_groups': task_groups,
            'selected_task_id': int(selected_task_id) if selected_task_id and selected_task_id.isdigit() else None,
        },
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
        },
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
