import calendar
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.time import WEEKDAYS, calculate_task_score, current_time
from ...models import Note, ScheduleItem, Subject, Task
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


def build_streak_state(completed_tasks):
    completed_dates = {
        (task.completed_at or task.created_at).date()
        for task in completed_tasks
        if task.completed_at or task.created_at
    }
    today = current_time().date()

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


def build_today_reminders(now, active_schedule_item, next_schedule_item, pending_tasks, schedule_terms):
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

    deadline_tasks = sorted(
        [task for task in pending_tasks if task.deadline],
        key=lambda task: task.deadline,
    )

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


@router.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    now = current_time().replace(tzinfo=None)
    tasks = db.query(Task).filter(Task.user_id == user.id).all()
    notes = db.query(Note).filter(Note.user_id == user.id).order_by(Note.created_at.desc()).all()
    pending_tasks = [task for task in tasks if not task.is_completed]
    completed_tasks = [task for task in tasks if task.is_completed]
    overdue_tasks = [task for task in pending_tasks if task.deadline and task.deadline < now]
    urgent_tasks = sorted(pending_tasks, key=calculate_task_score, reverse=True)[:5]
    streak = build_streak_state(completed_tasks)

    today_weekday = now.weekday()
    today_schedule = db.query(ScheduleItem).filter(
        ScheduleItem.user_id == user.id,
        ScheduleItem.weekday == today_weekday,
    ).order_by(ScheduleItem.start_time.asc()).all()
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
    today_notes = [note for note in notes if note.created_at and note.created_at.date() == now.date()][:3]
    recent_notes = notes[:3]
    today_focus_tasks = urgent_tasks[:3]
    today_reminders = build_today_reminders(
        now,
        active_schedule_item,
        next_schedule_item,
        pending_tasks,
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
        'subjects_count': db.query(Subject).filter(Subject.user_id == user.id).count(),
        'subjects': db.query(Subject).filter(Subject.user_id == user.id).order_by(Subject.name.asc()).all(),
        'pending_count': len(pending_tasks),
        'completed_count': len(completed_tasks),
        'overdue_count': len(overdue_tasks),
        'streak': streak,
        'urgent_tasks': urgent_tasks,
        'today_focus_tasks': today_focus_tasks,
        'today_reminders': today_reminders,
        'today_schedule': today_schedule,
        'today_notes': today_notes or recent_notes,
        'today_notes_are_recent': not bool(today_notes) and bool(recent_notes),
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
