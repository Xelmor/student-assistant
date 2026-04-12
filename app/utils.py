from datetime import datetime
from zoneinfo import ZoneInfo

from .settings import settings

APP_ZONE = ZoneInfo(settings.timezone)


def current_time() -> datetime:
    return datetime.now(APP_ZONE)


def current_date():
    return current_time().date()

WEEKDAYS = {
    0: 'Понедельник',
    1: 'Вторник',
    2: 'Среда',
    3: 'Четверг',
    4: 'Пятница',
    5: 'Суббота',
    6: 'Воскресенье',
}

PRIORITY_ORDER = {'high': 3, 'medium': 2, 'low': 1}
DIFFICULTY_ORDER = {'high': 3, 'medium': 2, 'low': 1}


def calculate_task_score(task) -> int:
    score = 0
    if task.deadline:
        days_left = (task.deadline - current_time().replace(tzinfo=None)).days
        if days_left <= 0:
            score += 10
        elif days_left <= 1:
            score += 8
        elif days_left <= 3:
            score += 6
        elif days_left <= 7:
            score += 4
        else:
            score += 2
    score += PRIORITY_ORDER.get(task.priority, 2) * 2
    score += DIFFICULTY_ORDER.get(task.difficulty, 2)
    return score
