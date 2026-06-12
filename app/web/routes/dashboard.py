import calendar
import random
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from ...core.database import get_db
from ...core.time import WEEKDAYS, current_time
from ...core.validation import normalize_bounded_text, normalize_choice
from ...models import AcademicEvent, Note, ScheduleItem, Subject, Task
from ..dependencies import (
    MOTIVATIONAL_QUOTES,
    get_schedule_terms,
    is_local_private_data_enabled,
    require_user,
    templates,
    validate_csrf,
)

router = APIRouter()

MONTH_NAMES_RU = {
    1: 'Январь',
    2: 'Февраль',
    3: 'Март',
    4: 'Апрель',
    5: 'Май',
    6: 'Июнь',
    7: 'Июль',
    8: 'Август',
    9: 'Сентябрь',
    10: 'Октябрь',
    11: 'Ноябрь',
    12: 'Декабрь',
}

PRIORITY_LABELS = {
    'high': 'Высокий приоритет',
    'medium': 'Средний приоритет',
    'low': 'Низкий приоритет',
}

ONBOARDING_STEPS = (
    {
        'key': 'subject',
        'title': 'Добавь первый предмет',
        'description': 'Создай дисциплину, чтобы связывать с ней задачи, заметки и расписание.',
        'action_label': 'Добавить предмет',
        'url': '/subjects#subject-create',
        'icon': 'book',
    },
    {
        'key': 'task',
        'title': 'Создай первую задачу',
        'description': 'Запиши ближайший дедлайн или домашнюю работу.',
        'action_label': 'Добавить задачу',
        'url': '/tasks#task-create',
        'icon': 'check',
    },
    {
        'key': 'schedule',
        'title': 'Настрой расписание',
        'description': 'Добавь пары по дням недели, чтобы видеть учебную нагрузку.',
        'action_label': 'Открыть расписание',
        'url': '/schedule#schedule-form-panel',
        'icon': 'calendar',
    },
    {
        'key': 'calendar',
        'title': 'Открой календарь',
        'description': 'Проверь неделю, добавь экзамены, дедлайны и важные события.',
        'action_label': 'Открыть календарь',
        'url': '/calendar?onboarding_step=calendar',
        'icon': 'star',
    },
)

ONBOARDING_ACCENTS = {'purple', 'blue', 'cyan', 'green', 'orange', 'pink'}
ONBOARDING_TIME_FORMATS = {'24', '12'}


def build_onboarding_state(db: Session, user) -> dict:
    completed_by_key = {
        'subject': db.query(Subject.id).filter(Subject.user_id == user.id).first() is not None,
        'task': db.query(Task.id).filter(Task.user_id == user.id).first() is not None,
        'schedule': (
            db.query(ScheduleItem.id)
            .filter(ScheduleItem.user_id == user.id)
            .first()
            is not None
        ),
        'calendar': bool(user.onboarding_calendar_opened) or (
            db.query(AcademicEvent.id)
            .filter(AcademicEvent.user_id == user.id)
            .first()
            is not None
        ),
    }
    completed_count = sum(completed_by_key.values())
    next_step_key = next(
        (step['key'] for step in ONBOARDING_STEPS if not completed_by_key[step['key']]),
        None,
    )
    steps = [
        {
            **step,
            'completed': completed_by_key[step['key']],
            'active': step['key'] == next_step_key,
        }
        for step in ONBOARDING_STEPS
    ]
    return {
        'visible': not bool(user.onboarding_completed),
        'steps': steps,
        'completed_count': completed_count,
        'total_count': len(ONBOARDING_STEPS),
        'percent': round((completed_count / len(ONBOARDING_STEPS)) * 100),
        'all_completed': completed_count == len(ONBOARDING_STEPS),
    }


def build_streak_state(completed_task_dates: list[date], today: date):
    completed_dates = {
        completed_date
        for completed_date in completed_task_dates
        if completed_date is not None
    }

    if not completed_dates:
        return {
            'days': 0,
            'headline': 'Стрик еще не начат',
            'message': 'Закрой первую задачу сегодня, чтобы зажечь серию.',
            'emoji': '✨',
        }

    streak_days = 0
    cursor = today if today in completed_dates else today - timedelta(days=1)
    while cursor in completed_dates:
        streak_days += 1
        cursor -= timedelta(days=1)

    if streak_days == 0:
        return {
            'days': 0,
            'headline': 'Стрик пока на паузе',
            'message': 'Сегодня можно вернуться в ритм и начать новую серию.',
            'emoji': '⚡',
        }

    return {
        'days': streak_days,
        'headline': f'Ты выполняешь задачи {streak_days} дня подряд',
        'message': 'Хороший темп. Закрой еще одну задачу, чтобы не прерывать серию.',
        'emoji': '🔥',
    }


def build_today_reminders(now, active_schedule_item, next_schedule_item, deadline_tasks, schedule_terms):
    reminders = []

    if active_schedule_item:
        reminders.append({
            'title': f'Сейчас идет {active_schedule_item.subject.name}',
            'time_label': f'До {active_schedule_item.end_time.strftime("%H:%M")}',
            'meta': f'{active_schedule_item.lesson_type or schedule_terms.singular.capitalize()}{f" · {active_schedule_item.room}" if active_schedule_item.room else ""}',
            'tone': 'live',
            'url': '/schedule',
        })
    elif next_schedule_item:
        reminders.append({
            'title': f'Следующее занятие: {next_schedule_item.subject.name}',
            'time_label': next_schedule_item.start_time.strftime('%H:%M'),
            'meta': f'{next_schedule_item.lesson_type or schedule_terms.singular.capitalize()}{f" · {next_schedule_item.room}" if next_schedule_item.room else ""}',
            'tone': 'upcoming',
            'url': '/schedule',
        })

    for task in deadline_tasks[:3]:
        is_overdue = task.deadline < now
        subject_label = task.subject.name if task.subject else 'Без предмета'
        reminders.append({
            'title': task.title,
            'time_label': (
                f'Просрочена {task.deadline.strftime("%d.%m %H:%M")}'
                if is_overdue else
                f'До {task.deadline.strftime("%d.%m %H:%M")}'
            ),
            'meta': f'{subject_label} · {PRIORITY_LABELS.get(task.priority, "Средний приоритет")}',
            'tone': 'overdue' if is_overdue else 'task',
            'url': f'/tasks?task={task.id}',
        })

    unique_reminders = []
    seen = set()
    for reminder in reminders:
        key = (reminder['title'], reminder['time_label'])
        if key in seen:
            continue
        seen.add(key)
        unique_reminders.append(reminder)

    return unique_reminders[:4]


def get_dashboard_task_counts(db: Session, user_id: int, now: datetime) -> dict[str, int]:
    pending_case = case((Task.is_completed.is_(False), 1), else_=0)
    completed_case = case((Task.is_completed.is_(True), 1), else_=0)
    overdue_case = case(
        ((Task.is_completed.is_(False)) & Task.deadline.is_not(None) & (Task.deadline < now), 1),
        else_=0,
    )

    pending_count, completed_count, overdue_count = (
        db.query(
            func.sum(pending_case),
            func.sum(completed_case),
            func.sum(overdue_case),
        )
        .filter(Task.user_id == user_id)
        .one()
    )

    return {
        'pending_count': int(pending_count or 0),
        'completed_count': int(completed_count or 0),
        'overdue_count': int(overdue_count or 0),
    }


def get_urgent_tasks(db: Session, user_id: int, now: datetime, limit: int = 5) -> list[Task]:
    deadline_score = case(
        (Task.deadline.is_(None), 0),
        (Task.deadline <= now, 10),
        (Task.deadline <= now + timedelta(days=1), 8),
        (Task.deadline <= now + timedelta(days=3), 6),
        (Task.deadline <= now + timedelta(days=7), 4),
        else_=2,
    )
    priority_score = case(
        (Task.priority == 'high', 6),
        (Task.priority == 'medium', 4),
        (Task.priority == 'low', 2),
        else_=4,
    )
    difficulty_score = case(
        (Task.difficulty == 'high', 3),
        (Task.difficulty == 'medium', 2),
        (Task.difficulty == 'low', 1),
        else_=2,
    )
    score = deadline_score + priority_score + difficulty_score

    return (
        db.query(Task)
        .options(joinedload(Task.subject))
        .filter(Task.user_id == user_id, Task.is_completed.is_(False))
        .order_by(score.desc(), Task.deadline.asc().nullslast(), Task.created_at.desc())
        .limit(limit)
        .all()
    )


def get_dashboard_deadline_tasks(db: Session, user_id: int, limit: int = 3) -> list[Task]:
    return (
        db.query(Task)
        .options(joinedload(Task.subject))
        .filter(Task.user_id == user_id, Task.is_completed.is_(False), Task.deadline.is_not(None))
        .order_by(Task.deadline.asc())
        .limit(limit)
        .all()
    )


def get_completed_task_dates(db: Session, user_id: int) -> list[date]:
    completed_tasks = (
        db.query(Task.completed_at, Task.created_at)
        .filter(Task.user_id == user_id, Task.is_completed.is_(True))
        .all()
    )
    return [(completed_at or created_at).date() for completed_at, created_at in completed_tasks if completed_at or created_at]


def get_today_schedule(db: Session, user_id: int, today_weekday: int) -> list[ScheduleItem]:
    return (
        db.query(ScheduleItem)
        .options(joinedload(ScheduleItem.subject))
        .filter(ScheduleItem.user_id == user_id, ScheduleItem.weekday == today_weekday)
        .order_by(ScheduleItem.start_time.asc())
        .all()
    )


def get_dashboard_notes(db: Session, user_id: int, now: datetime) -> tuple[list[Note], bool]:
    day_start = datetime.combine(now.date(), time.min)
    day_end = day_start + timedelta(days=1)
    today_notes = (
        db.query(Note)
        .filter(Note.user_id == user_id, Note.created_at >= day_start, Note.created_at < day_end)
        .order_by(Note.created_at.desc())
        .limit(3)
        .all()
    )
    if today_notes:
        return today_notes, False

    recent_notes = (
        db.query(Note)
        .filter(Note.user_id == user_id)
        .order_by(Note.created_at.desc())
        .limit(3)
        .all()
    )
    return recent_notes, bool(recent_notes)


@router.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    now = current_time()
    task_counts = get_dashboard_task_counts(db, user.id, now)
    urgent_tasks = get_urgent_tasks(db, user.id, now)
    deadline_tasks = get_dashboard_deadline_tasks(db, user.id)
    streak = build_streak_state(get_completed_task_dates(db, user.id), now.date())

    today_weekday = now.weekday()
    today_schedule = get_today_schedule(db, user.id, today_weekday)
    now_time = now.time()
    active_schedule_item = None
    next_schedule_item = None
    active_schedule_remaining_seconds = 0

    for item in today_schedule:
        if item.start_time <= now_time < item.end_time:
            active_schedule_item = item
            lesson_end = datetime.combine(now.date(), item.end_time)
            active_schedule_remaining_seconds = max(0, int((lesson_end - now).total_seconds()))
            break
        if now_time < item.start_time and next_schedule_item is None:
            next_schedule_item = item

    schedule_terms = get_schedule_terms(user)
    onboarding = build_onboarding_state(db, user)
    onboarding_chat_status = request.query_params.get('onboarding_chat')
    dashboard_notes, today_notes_are_recent = get_dashboard_notes(db, user.id, now)
    today_focus_tasks = urgent_tasks[:3]
    today_reminders = build_today_reminders(
        now,
        active_schedule_item,
        next_schedule_item,
        deadline_tasks,
        schedule_terms,
    )

    month_matrix = calendar.Calendar(firstweekday=0).monthdatescalendar(now.year, now.month)
    calendar_days = []
    for week in month_matrix:
        for date_value in week:
            calendar_days.append({
                'day': date_value.day,
                'in_month': date_value.month == now.month,
                'is_today': date_value == now.date(),
            })

    context = {
        'user': user,
        'local_private_data_available': is_local_private_data_enabled(request),
        'pending_count': task_counts['pending_count'],
        'completed_count': task_counts['completed_count'],
        'overdue_count': task_counts['overdue_count'],
        'streak': streak,
        'urgent_tasks': urgent_tasks,
        'today_focus_tasks': today_focus_tasks,
        'today_reminders': today_reminders,
        'today_schedule': today_schedule,
        'today_notes': dashboard_notes,
        'today_notes_are_recent': today_notes_are_recent,
        'active_schedule_item': active_schedule_item,
        'next_schedule_item': next_schedule_item,
        'active_schedule_remaining_seconds': active_schedule_remaining_seconds,
        'weekdays': WEEKDAYS,
        'now': now,
        'calendar_days': calendar_days,
        'calendar_month_name': MONTH_NAMES_RU[now.month],
        'motivation_quote': random.choice(MOTIVATIONAL_QUOTES),
        'schedule_terms': schedule_terms,
        'onboarding': onboarding,
        'onboarding_status': request.query_params.get('onboarding'),
        'onboarding_chat_visible': not bool(user.onboarding_chat_completed),
        'onboarding_chat_status': onboarding_chat_status,
        'onboarding_chat_restart': onboarding_chat_status == 'restart',
    }
    return templates.TemplateResponse(request, 'dashboard/dashboard.html', context)


@router.post('/onboarding/complete')
def complete_onboarding(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    onboarding = build_onboarding_state(db, user)
    if not onboarding['all_completed']:
        return RedirectResponse('/dashboard?onboarding=incomplete', status_code=302)

    user.onboarding_completed = True
    db.commit()
    return RedirectResponse('/dashboard?onboarding=completed', status_code=302)


@router.post('/onboarding/skip')
def skip_onboarding(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    user.onboarding_completed = True
    db.commit()
    return RedirectResponse('/dashboard?onboarding=skipped', status_code=302)


def _onboarding_chat_response(request: Request, location: str, payload: dict):
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JSONResponse(payload)
    return RedirectResponse(location, status_code=302)


@router.post('/onboarding/chat/complete')
def complete_onboarding_chat(
    request: Request,
    display_name: str = Form(''),
    group_name: str = Form(''),
    course: int | None = Form(None),
    accent: str = Form('purple'),
    time_format: str = Form('24'),
    destination: str = Form('/dashboard'),
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    try:
        normalized_display_name = normalize_bounded_text(
            display_name,
            label='Имя',
            max_length=40,
        )
        normalized_group_name = normalize_bounded_text(
            group_name,
            label='Группа',
            max_length=50,
        )
        if course is not None and not 1 <= course <= 12:
            raise ValueError('Курс должен быть числом от 1 до 12.')
        normalized_accent = normalize_choice(
            accent,
            label='Цвет акцента',
            allowed=ONBOARDING_ACCENTS,
        )
        normalized_time_format = normalize_choice(
            time_format,
            label='Формат времени',
            allowed=ONBOARDING_TIME_FORMATS,
        )
    except ValueError as error:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JSONResponse({'ok': False, 'error': str(error)}, status_code=422)
        return RedirectResponse('/dashboard?onboarding_chat=invalid', status_code=302)

    if normalized_display_name:
        user.display_name = normalized_display_name
    if normalized_group_name:
        user.group_name = normalized_group_name
    if course is not None:
        user.course = course
    user.onboarding_chat_completed = True
    db.commit()

    current_display_name = user.display_name or user.username
    request.session['username'] = current_display_name
    request.session['username_initial'] = (current_display_name[:1] or 'U').upper()
    redirect_to = (
        '/subjects#subject-create'
        if destination == '/subjects#subject-create'
        else '/dashboard?onboarding_chat=completed'
    )
    return _onboarding_chat_response(
        request,
        redirect_to,
        {
            'ok': True,
            'redirect': redirect_to,
            'displayName': current_display_name,
            'accent': normalized_accent,
            'timeFormat': normalized_time_format,
        },
    )


@router.post('/onboarding/chat/skip')
def skip_onboarding_chat(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    user.onboarding_chat_completed = True
    db.commit()
    return _onboarding_chat_response(
        request,
        '/dashboard?onboarding_chat=skipped',
        {'ok': True, 'redirect': '/dashboard?onboarding_chat=skipped'},
    )


@router.post('/onboarding/chat/restart')
def restart_onboarding_chat(
    request: Request,
    _: None = Depends(validate_csrf),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    user.onboarding_chat_completed = False
    db.commit()
    return RedirectResponse('/dashboard?onboarding_chat=restart', status_code=302)
