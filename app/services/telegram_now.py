"""A compact view of the current lesson using the site's effective calendar."""
from datetime import datetime, timedelta
from html import escape

from sqlalchemy.orm import Session

from ..models import User
from .telegram_day import TelegramCalendar, format_interval
from .telegram_digest import digest_local_datetime


LOOKAHEAD_DAYS = 7


def _lesson_text(lesson: dict, *, start_only: bool = False) -> str:
    title = escape(lesson['title'], quote=False)
    time_label = lesson['start'].strftime('%H:%M')
    if not start_only:
        time_label += '–' + lesson['end'].strftime('%H:%M')
    room = (lesson.get('room') or '').strip()
    if room:
        time_label += f' · Ауд. {escape(room, quote=False)}'
    return f'🎓 <b>{title}</b>\n{time_label}'


def build_now_message(db: Session, user: User, *, now_utc: datetime | None = None) -> str:
    # Schedule times are local wall-clock values, as in /today and the calendar.
    # Resolve one user/project-local instant for the whole response, never host time.
    local_now = digest_local_datetime(user, now_utc).replace(tzinfo=None)
    calendar = TelegramCalendar(db, user, local_now)
    today = calendar.today
    day = calendar.day()
    lessons, current, upcoming = day.lessons, day.current, day.upcoming
    if day.status == 'incomplete':
        return '📍 Сейчас: уточни время занятий\n\nВ расписании есть занятия без полного времени. Открой «Сегодня» или календарь на сайте.'

    if current:
        message = (
            '📍 <b>Сейчас</b>\n\n'
            f'{_lesson_text(current)}\n\n'
            f'До конца: {format_interval(current["end"] - local_now)}'
        )
        if upcoming:
            message += (
                f'\n\nДальше:\n{_lesson_text(upcoming, start_only=True)}\n'
                f'Через {format_interval(upcoming["start"] - local_now)}'
            )
        else:
            message += '\n\nЭто последняя пара на сегодня.'
        return message

    if upcoming:
        before_first = day.status == 'before'
        heading = '📍 Учебный день ещё не начался' if before_first else '📍 Свободное окно'
        label = 'Первая пара:' if before_first else 'Следующая пара:'
        return (
            f'{heading}\n\n{label}\n{_lesson_text(upcoming)}\n\n'
            f'Через {format_interval(upcoming["start"] - local_now)}'
        )

    if lessons:
        message = '✅ На сегодня занятия закончились.'
        tomorrow_day = calendar.day(today + timedelta(days=1))
        tomorrow = tomorrow_day.lessons
        if tomorrow_day.status == 'incomplete':
            return message + '\n\nЗавтра есть занятия, но их время указано не полностью. Проверь календарь на сайте.'
        if tomorrow:
            return message + f'\n\nСледующая пара завтра:\n{_lesson_text(tomorrow[0])}'
        return message + '\n\nНа завтра занятий нет.'

    message = '🌿 Сегодня занятий нет.'
    for offset in range(1, LOOKAHEAD_DAYS + 1):
        day = today + timedelta(days=offset)
        future_day = calendar.day(day)
        future = future_day.lessons
        if not future:
            continue
        if future_day.status == 'incomplete':
            return message + f'\n\nБлижайший учебный день — {day:%d.%m}, но время занятий указано не полностью. Проверь календарь на сайте.'
        label = 'Следующая пара завтра:' if offset == 1 else f'Ближайшая пара — {day:%d.%m}:'
        return message + f'\n\n{label}\n{_lesson_text(future[0])}'
    return message + f'\n\nВ ближайшие {LOOKAHEAD_DAYS} дней занятий нет.'
