from __future__ import annotations

from html import escape

from ..models import Task, User


VALID_DEADLINE_REMINDER_HOURS = (2, 6, 24)
PRIORITY_LABELS = {'high': 'высокий', 'medium': 'средний', 'low': 'низкий'}
PRIORITY_MARKERS = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
MESSAGE_DIVIDER = '━━━━━━━━━━━━━━'


def deadline_reminder_hours(user: User) -> int:
    hours = user.telegram_deadline_reminder_hours or 24
    return hours if hours in VALID_DEADLINE_REMINDER_HOURS else 24


def deadline_reminder_date_key(task: Task, reminder_hours: int) -> str:
    deadline_key = task.deadline.isoformat(timespec='minutes') if task.deadline else 'none'
    return f'{deadline_key}:{reminder_hours}'


def build_deadline_reminder_message(task: Task, reminder_hours: int) -> str:
    priority_key = task.priority or 'medium'
    priority = PRIORITY_LABELS.get(priority_key, 'средний')
    marker = PRIORITY_MARKERS.get(priority_key, '🟡')
    deadline = task.deadline.strftime('%d.%m.%Y в %H:%M')
    return (
        '⏰ <b>Скоро дедлайн</b>\n\n'
        f'📌 <b>{escape(task.title, quote=False)}</b>\n\n'
        f'Дедлайн: <b>{deadline}</b>\n'
        f'Осталось: примерно <b>{reminder_hours} ч.</b>\n'
        f'Приоритет: {marker} {priority}\n\n'
        f'{MESSAGE_DIVIDER}\n\n'
        '<i>Лучше закрыть задачу заранее, чтобы не делать всё '
        'в последний момент 🎓</i>'
    )
