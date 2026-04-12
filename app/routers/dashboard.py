import calendar
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ScheduleItem, Subject, Task
from ..utils import WEEKDAYS, calculate_task_score
from .common import MOTIVATIONAL_QUOTES, get_schedule_terms, is_local_private_data_enabled, require_user, templates

router = APIRouter()


def build_streak_state(completed_tasks):
    completed_dates = {
        (task.completed_at or task.created_at).date()
        for task in completed_tasks
        if task.completed_at or task.created_at
    }
    today = datetime.now().date()

    if not completed_dates:
        return {
            'days': 0,
            'headline': '\u0421\u0442\u0440\u0438\u043a \u0435\u0449\u0435 \u043d\u0435 \u043d\u0430\u0447\u0430\u0442',
            'message': '\u0417\u0430\u043a\u0440\u043e\u0439 \u043f\u0435\u0440\u0432\u0443\u044e \u0437\u0430\u0434\u0430\u0447\u0443 \u0441\u0435\u0433\u043e\u0434\u043d\u044f, \u0447\u0442\u043e\u0431\u044b \u0437\u0430\u0436\u0435\u0447\u044c \u0441\u0435\u0440\u0438\u044e.',
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
            'headline': '\u0421\u0442\u0440\u0438\u043a \u043f\u043e\u043a\u0430 \u043d\u0430 \u043f\u0430\u0443\u0437\u0435',
            'message': '\u0421\u0435\u0433\u043e\u0434\u043d\u044f \u043c\u043e\u0436\u043d\u043e \u0432\u0435\u0440\u043d\u0443\u0442\u044c\u0441\u044f \u0432 \u0440\u0438\u0442\u043c \u0438 \u043d\u0430\u0447\u0430\u0442\u044c \u043d\u043e\u0432\u0443\u044e \u0441\u0435\u0440\u0438\u044e.',
            'emoji': '⚡',
        }

    return {
        'days': streak_days,
        'headline': f'\u0422\u044b \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0448\u044c \u0437\u0430\u0434\u0430\u0447\u0438 {streak_days} \u0434\u043d\u044f \u043f\u043e\u0434\u0440\u044f\u0434',
        'message': '\u0425\u043e\u0440\u043e\u0448\u0438\u0439 \u0442\u0435\u043c\u043f. \u0417\u0430\u043a\u0440\u043e\u0439 \u0435\u0449\u0435 \u043e\u0434\u043d\u0443 \u0437\u0430\u0434\u0430\u0447\u0443, \u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u043f\u0440\u0435\u0440\u044b\u0432\u0430\u0442\u044c \u0441\u0435\u0440\u0438\u044e.',
        'emoji': '🔥',
    }


@router.get('/dashboard', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if not user:
        return RedirectResponse('/login', status_code=302)

    now = datetime.now()
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
        'motivation_quote': random.choice(MOTIVATIONAL_QUOTES),
        'schedule_terms': schedule_terms,
    }
    return templates.TemplateResponse(request, 'dashboard.html', context)
