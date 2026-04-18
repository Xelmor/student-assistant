import calendar
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.time import WEEKDAYS, calculate_task_score, current_time
from ...models import ScheduleItem, Subject, Task
from ..dependencies import MOTIVATIONAL_QUOTES, get_schedule_terms, is_local_private_data_enabled, require_user, templates

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


@router.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    now = current_time().replace(tzinfo=None)
    tasks = db.query(Task).filter(Task.user_id == user.id).all()
    pending_tasks = [t for t in tasks if not t.is_completed]
    completed_tasks = [t for t in tasks if t.is_completed]
    overdue_tasks = [t for t in pending_tasks if t.deadline and t.deadline < now]
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
        'today_schedule': today_schedule,
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
