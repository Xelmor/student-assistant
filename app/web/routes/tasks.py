from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.time import WEEKDAYS, calculate_task_score, current_time
from ...models import ScheduleItem, Subject, Task
from ...services.recurring_tasks import (
    RECURRENCE_NONE,
    RECURRENCE_OPTIONS,
    calculate_next_deadline,
    get_recurrence_label,
    normalize_recurrence_settings,
    recurrence_requires_deadline,
)
from ...services.task_schedule_links import get_task_anchor_datetime, parse_scheduled_for_date, validate_schedule_link
from ..dependencies import require_user, templates, validate_csrf

router = APIRouter()


def pluralize_days(value: int) -> str:
    if value % 10 == 1 and value % 100 != 11:
        return 'день'
    if value % 10 in {2, 3, 4} and value % 100 not in {12, 13, 14}:
        return 'дня'
    return 'дней'


def build_tasks_redirect(selected_task_id: int | None = None, form_error: str | None = None) -> str:
    params = {}
    if selected_task_id is not None:
        params['task'] = str(selected_task_id)
    if form_error:
        params['form_error'] = form_error
    query = urlencode(params)
    return f'/tasks?{query}' if query else '/tasks'


def format_schedule_option(item: ScheduleItem) -> str:
    return (
        f"{WEEKDAYS[item.weekday]} · {item.start_time.strftime('%H:%M')}"
        f" - {item.end_time.strftime('%H:%M')} · {item.subject.name}"
    )


def build_task_schedule_summary(task: Task) -> tuple[str | None, str | None]:
    if task.scheduled_for_date and task.schedule_item:
        return (
            'Привязано к занятию',
            (
                f"{task.scheduled_for_date.strftime('%d.%m.%Y')} · "
                f"{WEEKDAYS[task.schedule_item.weekday]} · "
                f"{task.schedule_item.start_time.strftime('%H:%M')} - "
                f"{task.schedule_item.end_time.strftime('%H:%M')}"
            ),
        )

    if task.scheduled_for_date:
        return ('Привязано к дате', task.scheduled_for_date.strftime('%d.%m.%Y'))

    if task.schedule_item:
        return (
            'Шаблон пары',
            (
                f"{WEEKDAYS[task.schedule_item.weekday]} · "
                f"{task.schedule_item.start_time.strftime('%H:%M')} - "
                f"{task.schedule_item.end_time.strftime('%H:%M')}"
            ),
        )

    return None, None


def build_deadline_state(task: Task, now: datetime) -> dict[str, str | int | None]:
    anchor_datetime = get_task_anchor_datetime(task)

    if task.is_completed:
        return {
            'tone': 'done',
            'label': 'Выполнено',
            'detail': 'Задача закрыта',
            'sort_rank': -1,
        }

    if not anchor_datetime:
        return {
            'tone': 'neutral',
            'label': 'Без дедлайна',
            'detail': 'Срок не указан',
            'sort_rank': 0,
        }

    delta = anchor_datetime - now
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
            'detail': f'До {anchor_datetime.strftime("%H:%M")}',
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
        'detail': f'До {anchor_datetime.strftime("%d.%m.%Y")}',
        'sort_rank': 1,
    }


def enrich_tasks(tasks: list[Task], now: datetime) -> list[Task]:
    for task in tasks:
        anchor_datetime = get_task_anchor_datetime(task)
        task.deadline_state = build_deadline_state(task, now)
        task.smart_score = calculate_task_score(task) if not task.is_completed else -1
        if task.deadline:
            task.smart_deadline_text = task.deadline.strftime('%d.%m.%Y %H:%M')
        elif task.scheduled_for_date:
            task.smart_deadline_text = task.scheduled_for_date.strftime('%d.%m.%Y')
        else:
            task.smart_deadline_text = '—'
        task.recurrence_label = get_recurrence_label(task.recurrence_type, task.recurrence_interval_days)
        task.schedule_link_label, task.schedule_link_detail = build_task_schedule_summary(task)
        task.anchor_datetime = anchor_datetime

    return sorted(
        tasks,
        key=lambda task: (
            task.is_completed,
            -int(task.deadline_state['sort_rank']),
            -int(task.smart_score),
            task.anchor_datetime or datetime.max,
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


def parse_task_form(
    deadline: str,
    scheduled_for_date: str,
    recurrence_type: str,
    recurrence_interval_days: str,
) -> tuple[datetime | None, date | None, str, int | None]:
    deadline_value = datetime.strptime(deadline, '%Y-%m-%dT%H:%M') if deadline else None
    scheduled_for_date_value = parse_scheduled_for_date(scheduled_for_date)
    normalized_recurrence_type, normalized_recurrence_interval = normalize_recurrence_settings(
        recurrence_type,
        recurrence_interval_days,
    )

    if recurrence_requires_deadline(normalized_recurrence_type) and deadline_value is None:
        raise ValueError('Для повторяющейся задачи нужно указать первый дедлайн.')

    return deadline_value, scheduled_for_date_value, normalized_recurrence_type, normalized_recurrence_interval


def resolve_schedule_item_for_user(
    user_id: int,
    db: Session,
    schedule_item_id_raw: str | None,
) -> ScheduleItem | None:
    if not schedule_item_id_raw:
        return None
    if not str(schedule_item_id_raw).isdigit():
        raise ValueError('Не удалось определить выбранную пару.')

    schedule_item = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.id == int(schedule_item_id_raw), ScheduleItem.user_id == user_id)
        .first()
    )
    if not schedule_item:
        raise ValueError('Выбранная пара не найдена.')
    return schedule_item


@router.get('/tasks', response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    selected_task_id = request.query_params.get('task')
    form_error = request.query_params.get('form_error')
    now = current_time().replace(tzinfo=None)
    raw_tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id)
        .all()
    )
    tasks = enrich_tasks(raw_tasks, now)
    subjects = db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all()
    schedule_items = (
        db.query(ScheduleItem)
        .filter(ScheduleItem.user_id == user.id)
        .order_by(ScheduleItem.weekday.asc(), ScheduleItem.start_time.asc())
        .all()
    )

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
            'schedule_items': schedule_items,
            'schedule_options': [(item.id, format_schedule_option(item)) for item in schedule_items],
            'now': now,
            'smart_counts': smart_counts,
            'task_groups': task_groups,
            'selected_task_id': int(selected_task_id) if selected_task_id and selected_task_id.isdigit() else None,
            'form_error': form_error,
            'recurrence_options': RECURRENCE_OPTIONS,
        },
    )


@router.post('/tasks/add')
async def add_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    scheduled_for_date: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    recurrence_type: str = Form(RECURRENCE_NONE),
    recurrence_interval_days: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    form = await request.form()
    schedule_item_id_raw = form.get('schedule_item_id')

    normalized_title = title.strip()
    if not normalized_title:
        return RedirectResponse(build_tasks_redirect(form_error='Название задачи не может быть пустым.'), status_code=302)

    try:
        deadline_value, scheduled_for_date_value, normalized_recurrence_type, normalized_recurrence_interval = parse_task_form(
            deadline,
            scheduled_for_date,
            recurrence_type,
            recurrence_interval_days,
        )
        schedule_item = resolve_schedule_item_for_user(user.id, db, schedule_item_id_raw)
        validate_schedule_link(schedule_item, scheduled_for_date_value)
    except ValueError as error:
        return RedirectResponse(build_tasks_redirect(form_error=str(error)), status_code=302)

    resolved_subject_id = subject_id if subject_id else None
    if schedule_item:
        resolved_subject_id = schedule_item.subject_id

    if resolved_subject_id:
        subject = db.query(Subject).filter(Subject.id == resolved_subject_id, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse(build_tasks_redirect(form_error='Предмет для задачи не найден.'), status_code=302)

    task = Task(
        user_id=user.id,
        subject_id=resolved_subject_id,
        title=normalized_title,
        description=description.strip() or None,
        deadline=deadline_value,
        scheduled_for_date=scheduled_for_date_value,
        schedule_item_id=schedule_item.id if schedule_item else None,
        priority=priority,
        difficulty=difficulty,
        recurrence_type=normalized_recurrence_type,
        recurrence_interval_days=normalized_recurrence_interval,
    )
    db.add(task)
    db.flush()

    if task.recurrence_type != RECURRENCE_NONE:
        task.recurrence_group_id = task.id

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
async def edit_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(''),
    subject_id: int | None = Form(None),
    deadline: str = Form(''),
    scheduled_for_date: str = Form(''),
    priority: str = Form('medium'),
    difficulty: str = Form('medium'),
    recurrence_type: str = Form(RECURRENCE_NONE),
    recurrence_interval_days: str = Form(''),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        return RedirectResponse('/tasks', status_code=302)

    form = await request.form()
    schedule_item_id_raw = form.get('schedule_item_id')

    normalized_title = title.strip()
    if not normalized_title:
        return RedirectResponse(
            build_tasks_redirect(selected_task_id=task_id, form_error='Название задачи не может быть пустым.'),
            status_code=302,
        )

    try:
        deadline_value, scheduled_for_date_value, normalized_recurrence_type, normalized_recurrence_interval = parse_task_form(
            deadline,
            scheduled_for_date,
            recurrence_type,
            recurrence_interval_days,
        )
        schedule_item = resolve_schedule_item_for_user(user.id, db, schedule_item_id_raw)
        validate_schedule_link(schedule_item, scheduled_for_date_value)
    except ValueError as error:
        return RedirectResponse(build_tasks_redirect(selected_task_id=task_id, form_error=str(error)), status_code=302)

    resolved_subject_id = subject_id if subject_id else None
    if schedule_item:
        resolved_subject_id = schedule_item.subject_id

    if resolved_subject_id:
        subject = db.query(Subject).filter(Subject.id == resolved_subject_id, Subject.user_id == user.id).first()
        if not subject:
            return RedirectResponse(build_tasks_redirect(selected_task_id=task_id, form_error='Предмет для задачи не найден.'), status_code=302)

    task.title = normalized_title
    task.description = description.strip() or None
    task.subject_id = resolved_subject_id
    task.deadline = deadline_value
    task.scheduled_for_date = scheduled_for_date_value
    task.schedule_item_id = schedule_item.id if schedule_item else None
    task.priority = priority
    task.difficulty = difficulty
    task.recurrence_type = normalized_recurrence_type
    task.recurrence_interval_days = normalized_recurrence_interval
    if task.recurrence_type != RECURRENCE_NONE and task.recurrence_group_id is None:
        task.recurrence_group_id = task.id
    db.commit()
    return RedirectResponse('/tasks', status_code=302)


@router.post('/tasks/toggle/{task_id}')
def toggle_task(task_id: int, request: Request, _: None = Depends(validate_csrf), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if task:
        now = current_time().replace(tzinfo=None)
        is_marking_completed = not task.is_completed

        task.is_completed = is_marking_completed
        task.completed_at = now if is_marking_completed else None

        if is_marking_completed and task.recurrence_type != RECURRENCE_NONE:
            group_id = task.recurrence_group_id or task.id
            task.recurrence_group_id = group_id
            next_deadline = calculate_next_deadline(
                task.deadline,
                task.recurrence_type,
                task.recurrence_interval_days,
            )

            if next_deadline is not None:
                existing_next_task = (
                    db.query(Task)
                    .filter(
                        Task.user_id == user.id,
                        Task.recurrence_group_id == group_id,
                        Task.deadline == next_deadline,
                        Task.is_completed.is_(False),
                    )
                    .first()
                )

                if not existing_next_task:
                    db.add(
                        Task(
                            user_id=task.user_id,
                            subject_id=task.subject_id,
                            title=task.title,
                            description=task.description,
                            deadline=next_deadline,
                            scheduled_for_date=task.scheduled_for_date,
                            schedule_item_id=task.schedule_item_id,
                            priority=task.priority,
                            difficulty=task.difficulty,
                            is_completed=False,
                            completed_at=None,
                            recurrence_group_id=group_id,
                            recurrence_type=task.recurrence_type,
                            recurrence_interval_days=task.recurrence_interval_days,
                            created_at=now,
                        )
                    )

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
