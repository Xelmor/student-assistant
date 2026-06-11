import calendar
import random
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from ...core.database import get_db
from ...core.time import WEEKDAYS, current_time
from ...models import Note, ScheduleItem, Task
from ..dependencies import (
    MOTIVATIONAL_QUOTES,
    get_schedule_terms,
    is_local_private_data_enabled,
    require_user,
    templates,
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
    }
    return templates.TemplateResponse(request, 'dashboard/dashboard.html', context)
