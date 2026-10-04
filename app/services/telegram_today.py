"""Short daily summary and expanded schedule over the shared effective day."""
from datetime import datetime
from html import escape

from sqlalchemy.orm import Session

from ..models import Task, User
from .calendar_service import MONTH_NAMES_RU_GENITIVE
from .task_schedule_links import get_task_anchor_datetime
from .telegram_day import TelegramCalendar, format_interval, has_complete_time
from .telegram_digest import digest_local_datetime


DIVIDER = '━━━━━━━━━━━━━━'


def plural(count: int, one: str, few: str, many: str) -> str:
    if 11 <= count % 100 <= 14:
        word = many
    elif count % 10 == 1:
        word = one
    elif 2 <= count % 10 <= 4:
        word = few
    else:
        word = many
    return f'{count} {word}'


def _room(lesson: dict) -> str:
    room = (lesson.get('room') or '').strip()
    return f'Ауд. {escape(room, quote=False)}' if room else ''


def _time(lesson: dict) -> str:
    if has_complete_time(lesson):
        return f'{lesson["start"]:%H:%M}–{lesson["end"]:%H:%M}'
    start, end = lesson.get('raw_start_time'), lesson.get('raw_end_time')
    if start:
        return f'С {start}, окончание не указано'
    if end:
        return f'До {end}, начало не указано'
    return 'Время не указано'


def _compact_lesson(lesson: dict, timing: str) -> str:
    details = ' · '.join(part for part in (_room(lesson), timing) if part)
    return f'{escape(lesson["title"], quote=False)} · {_time(lesson)}\n{details}'


def _schedule_summary(calendar: TelegramCalendar) -> str:
    day = calendar.day()
    if day.status == 'empty':
        return '🌿 Сегодня без занятий'
    if day.status == 'finished':
        return '✅ Занятия на сегодня закончились'
    if day.status == 'incomplete':
        return '📍 Сейчас\nВремя занятий указано не полностью. Открой «🗓 Расписание».'
    if day.current:
        message = '📍 <b>Сейчас</b>\n' + _compact_lesson(
            day.current, f'до конца: {format_interval(day.current["end"] - calendar.now)}',
        )
    else:
        status = 'Учебный день ещё не начался' if day.status == 'before' else 'Свободное окно'
        message = f'📍 <b>Сейчас</b>\n{status}'
    if day.upcoming:
        message += '\n\nДальше:\n' + _compact_lesson(
            day.upcoming, f'через {format_interval(day.upcoming["start"] - calendar.now)}',
        )
    elif day.current:
        message += '\n\nЭто последняя пара на сегодня.'
    return message


def _task_rank(task: Task, now: datetime) -> int:
    anchor = get_task_anchor_datetime(task)
    if anchor and anchor < now:
        return 0
    if anchor and anchor.date() == now.date():
        return 1
    if task.priority == 'high':
        return 2
    return 3 if anchor else 4


def _task_line(task: Task, now: datetime) -> str:
    anchor = get_task_anchor_datetime(task)
    rank = _task_rank(task, now)
    marker = '🔴' if rank in {0, 2} else '🟡' if rank == 1 else '🟢'
    details = []
    if anchor:
        if anchor.date() == now.date():
            details.append(f'до {anchor:%H:%M}' if task.deadline or task.schedule_item_id else 'сегодня')
        else:
            label = f'{anchor:%d.%m}'
            if anchor.year != now.year:
                label += f'.{anchor:%Y}'
            if task.deadline or task.schedule_item_id:
                label += f' {anchor:%H:%M}'
            details.append(f'до {label}')
    if rank == 0:
        details.append('просрочено')
    elif rank == 2:
        details.append('высокий приоритет')
    return ' · '.join([f'{marker} {escape(task.title, quote=False)}', *details])


def build_today_summary(db: Session, user: User, *, now_utc: datetime | None = None) -> str:
    calendar = TelegramCalendar(db, user, digest_local_datetime(user, now_utc))
    now, today = calendar.now, calendar.today
    tasks = db.query(Task).filter(Task.user_id == user.id, Task.is_completed.is_(False)).all()
    deadlines = sum(
        anchor is not None and anchor.date() == today
        for anchor in (get_task_anchor_datetime(task) for task in tasks)
    )
    lessons = calendar.day().lessons
    header = f'📅 <b>Сегодня</b>, {today.day} {MONTH_NAMES_RU_GENITIVE[today.month]}'
    counters = '\n'.join([
        '🎓 ' + plural(len(lessons), 'занятие', 'занятия', 'занятий'),
        '📌 ' + plural(len(tasks), 'активная задача', 'активные задачи', 'активных задач'),
        '⏰ ' + plural(deadlines, 'дедлайн сегодня', 'дедлайна сегодня', 'дедлайнов сегодня'),
    ])
    if not lessons and not tasks:
        return f'{header}\n\n{counters}\n\n{DIVIDER}\n\n🌿 Сегодня спокойно\n\nЗанятий нет.\nСрочных задач тоже нет.\n\nМожно выдохнуть или подготовиться заранее 🙂'

    important = sorted(
        (task for task in tasks if _task_rank(task, now) < 4),
        key=lambda task: (_task_rank(task, now), get_task_anchor_datetime(task) or datetime.max, task.id),
    )[:3]
    if important and _task_rank(important[0], now) < 3:
        task_section = '🔴 <b>Главное на сегодня</b>\n'
    elif important:
        task_section = 'На сегодня срочных задач нет ✅\n\n📌 <b>Ближайшие задачи</b>\n'
    else:
        task_section = 'На сегодня срочных задач нет ✅'
    task_section += '\n'.join(_task_line(task, now) for task in important)
    return f'{header}\n\n{counters}\n\n{DIVIDER}\n\n{_schedule_summary(calendar)}\n\n{DIVIDER}\n\n{task_section}'


def build_today_schedule(db: Session, user: User, *, now_utc: datetime | None = None) -> str:
    calendar = TelegramCalendar(db, user, digest_local_datetime(user, now_utc))
    entries = []
    for lesson in calendar.day().lessons:
        lines = [_time(lesson), escape(lesson['title'], quote=False)]
        if _room(lesson):
            lines.append(_room(lesson))
        if lesson['type'] == 'schedule-change':
            # The model stores no original slot or original time. Do not infer a
            # fictitious old → new time from an unrelated weekly lesson.
            lines.append('🔄 Изменение расписания · разовая пара')
        entries.append((lesson['start'], '\n'.join(lines)))
    for lesson in calendar.cancelled_today():
        lines = [f'{lesson.start_time:%H:%M}–{lesson.end_time:%H:%M}',
                 escape(lesson.subject.name, quote=False), '❌ Отменено']
        entries.append((datetime.combine(calendar.today, lesson.start_time), '\n'.join(lines)))
    entries.sort(key=lambda entry: entry[0])
    body = '\n\n'.join(text for _, text in entries) if entries else '🌿 Сегодня без занятий'
    return f'🗓 <b>Расписание на сегодня</b>\n\n{body}'
