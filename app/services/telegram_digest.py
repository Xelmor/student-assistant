from __future__ import annotations

from datetime import UTC, date, datetime, time
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from ..core.config import settings
from ..models import ScheduleItem, Task, User
from .task_schedule_links import get_task_anchor_datetime


PRIORITY_ORDER = {'high': 0, 'medium': 1, 'low': 2}
PRIORITY_MARKERS = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
PRIORITY_LABELS = {'high': 'высокий', 'medium': 'средний', 'low': 'низкий'}
MONTH_NAMES_GENITIVE = {
    1: 'января',
    2: 'февраля',
    3: 'марта',
    4: 'апреля',
    5: 'мая',
    6: 'июня',
    7: 'июля',
    8: 'августа',
    9: 'сентября',
    10: 'октября',
    11: 'ноября',
    12: 'декабря',
}
MESSAGE_DIVIDER = '━━━━━━━━━━━━━━'


def resolve_digest_timezone_name(user: User) -> str:
    candidates = (
        user.telegram_morning_digest_timezone,
        settings.timezone,
        'UTC',
    )
    for candidate in candidates:
        if not candidate:
            continue
        try:
            ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
        return candidate
    return 'UTC'


def digest_local_datetime(
    user: User,
    now_utc: datetime | None = None,
) -> datetime:
    current = now_utc or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(ZoneInfo(resolve_digest_timezone_name(user)))


def digest_send_time(user: User) -> time:
    return user.telegram_morning_digest_time or time(hour=8)


def _html(value: object) -> str:
    return escape(str(value), quote=False)


def _task_deadline_label(task: Task, target_date: date) -> str:
    anchor = get_task_anchor_datetime(task)
    if anchor is None:
        return 'без даты'
    if anchor.date() == target_date:
        return f"сегодня в {anchor.strftime('%H:%M')}"
    return (
        f'{anchor.day} {MONTH_NAMES_GENITIVE[anchor.month]} '
        f'в {anchor.strftime("%H:%M")}'
    )


def _task_sort_key(task: Task, target_date: date) -> tuple:
    anchor = get_task_anchor_datetime(task)
    is_today = anchor is not None and anchor.date() == target_date
    return (
        not is_today,
        anchor is None,
        anchor or datetime.max,
        PRIORITY_ORDER.get(task.priority or 'medium', 1),
        task.created_at or datetime.min,
    )


def build_morning_digest_message(
    db: Session,
    user: User,
    *,
    target_date: date | None = None,
    current_local_time: time | None = None,
) -> str:
    local_now = digest_local_datetime(user)
    digest_date = target_date or local_now.date()
    local_time = current_local_time or local_now.time().replace(tzinfo=None)

    lessons = (
        db.query(ScheduleItem)
        .filter(
            ScheduleItem.user_id == user.id,
            ScheduleItem.weekday == digest_date.weekday(),
        )
        .order_by(ScheduleItem.start_time.asc())
        .all()
    )
    active_tasks = (
        db.query(Task)
        .filter(Task.user_id == user.id, Task.is_completed.is_(False))
        .all()
    )
    deadlines_today = [
        task
        for task in active_tasks
        if (
            (anchor := get_task_anchor_datetime(task)) is not None
            and anchor.date() == digest_date
        )
    ]
    upcoming_lessons = [
        lesson for lesson in lessons if lesson.start_time >= local_time
    ]
    nearest_lesson = upcoming_lessons[0] if upcoming_lessons else None

    name = user.display_name or user.username
    if not lessons and not active_tasks:
        return (
            f'🌅 <b>Доброе утро, {_html(name)}!</b>\n\n'
            f'{MESSAGE_DIVIDER}\n\n'
            'На сегодня ничего не запланировано ✅\n'
            'Можно спокойно повторить материал, закрыть старые задачи '
            'или немного отдохнуть.\n\n'
            f'{MESSAGE_DIVIDER}\n\n'
            '<i>Хорошего учебного дня 🎓</i>'
        )

    sections = [
        (
            f'🌅 <b>Доброе утро, {_html(name)}!</b> '
            '<i>Краткая сводка на сегодня</i>'
        ),
        MESSAGE_DIVIDER,
        (
            'Сегодня у тебя:\n\n'
            f'📅 Пар: <b>{len(lessons)}</b>\n'
            f'📌 Активных задач: <b>{len(active_tasks)}</b>\n'
            f'⏰ Дедлайнов сегодня: <b>{len(deadlines_today)}</b>'
        ),
        MESSAGE_DIVIDER,
    ]

    if nearest_lesson is not None:
        lesson_details = (
            f"🕘 {nearest_lesson.start_time.strftime('%H:%M')}–"
            f"{nearest_lesson.end_time.strftime('%H:%M')} — "
            f'<b>{_html(nearest_lesson.subject.name)}</b>'
        )
        if nearest_lesson.room:
            lesson_details += f'\nАудитория: {_html(nearest_lesson.room)}'
        sections.append(
            '<b>Ближайшая пара</b>\n\n' + lesson_details
        )

    top_tasks = sorted(
        active_tasks,
        key=lambda task: _task_sort_key(task, digest_date),
    )[:3]
    if top_tasks:
        rows = []
        for index, task in enumerate(top_tasks, start=1):
            marker = PRIORITY_MARKERS.get(task.priority or 'medium', '⚪')
            priority = PRIORITY_LABELS.get(task.priority or 'medium', 'средний')
            rows.append(
                f'{index}. {marker} <b>{_html(task.title)}</b>\n'
                f'   Дедлайн: {_task_deadline_label(task, digest_date)}\n'
                f'   Приоритет: {priority}'
            )
        sections.extend(
            [
                MESSAGE_DIVIDER,
                '<b>Главные задачи</b>\n\n' + '\n\n'.join(rows),
            ]
        )

    sections.extend(
        [
            MESSAGE_DIVIDER,
            '<i>Хорошего и продуктивного дня 🎓</i>',
        ]
    )
    return '\n\n'.join(sections)
